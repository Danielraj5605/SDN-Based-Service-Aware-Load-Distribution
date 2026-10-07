"""SDN-Based Service-Aware Load Distribution - Ryu application.

Run from the project root:
    ryu-manager controller/lb_controller.py

Clients send traffic to a virtual IP (VIP). For the first packet of every new
flow the controller classifies the service, scores each server on health,
bandwidth, latency, loss and service match, picks the best one and installs
OpenFlow rules that rewrite VIP <-> server for the rest of the flow.
"""
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from ryu.app.wsgi import WSGIApplication                                # noqa: E402
from ryu.base import app_manager                                        # noqa: E402
from ryu.controller import ofp_event                                    # noqa: E402
from ryu.controller.handler import (CONFIG_DISPATCHER, DEAD_DISPATCHER,  # noqa: E402
                                    MAIN_DISPATCHER, set_ev_cls)
from ryu.lib import hub                                                 # noqa: E402
from ryu.lib.packet import (arp, ether_types, ethernet, icmp, in_proto,  # noqa: E402
                            ipv4, packet, tcp, udp)
from ryu.ofproto import ofproto_v1_3                                    # noqa: E402

import packets                                                          # noqa: E402
from classifier import ServiceClassifier                                # noqa: E402
from config_loader import (ROUND_ROBIN, WEIGHT_KEYS, ConfigError,       # noqa: E402
                           load_config, normalise_mode, validate_weights)
from csv_logger import CsvLog                                           # noqa: E402
from decision_engine import DecisionEngine                              # noqa: E402
from flow_manager import FlowManager, make_cookie                       # noqa: E402
from network_monitor import NetworkMonitor                              # noqa: E402
from rest_api import APP_KEY, LBRestController                          # noqa: E402
from server_monitor import ServerMonitor                                # noqa: E402

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DEFAULT_CONFIG = os.path.join(PROJECT_ROOT, 'config.yaml')
LOG_DIR = os.path.join(PROJECT_ROOT, 'logs')


class ServiceAwareLoadBalancer(app_manager.RyuApp):
    OFP_VERSIONS = [ofproto_v1_3.OFP_VERSION]
    _CONTEXTS = {'wsgi': WSGIApplication}

    def __init__(self, *args, **kwargs):
        super(ServiceAwareLoadBalancer, self).__init__(*args, **kwargs)
        config_path = os.environ.get('SDN_LB_CONFIG', DEFAULT_CONFIG)
        self.cfg = load_config(config_path)
        self.mode = self.cfg.mode
        self.servers = self.cfg.servers
        self.server_by_ip = {s.ip: s for s in self.servers}

        self.classifier = ServiceClassifier(self.cfg.services, self.cfg.dscp_map)
        self.net_mon = NetworkMonitor(self.cfg, self.servers, self.logger)
        self.srv_mon = ServerMonitor(self.cfg, self.servers, self.logger)
        self.engine = DecisionEngine(self.cfg)
        self.flows = FlowManager(self.cfg)

        self.datapath = None
        self.mac_to_port = {}       # plain L2 learning for non-VIP traffic (ARP etc.)
        self.sticky = {}            # flow key -> {'server', 'cookie', 'time'}
        self.active = {}            # cookie -> details of an installed load-balanced flow
        self._flow_seq = 0
        self.decision_count = 0
        self.decision_ms = []       # recent decision times, for NFR-1 (decision latency)
        self.migrations = 0

        self.decision_log = CsvLog(os.path.join(LOG_DIR, 'decisions.csv'), [
            'time', 'mode', 'client', 'proto', 'src_port', 'dst_port', 'service',
            'server', 'reason', 'decision_ms', 'scores'])
        self.metrics_log = CsvLog(os.path.join(LOG_DIR, 'metrics.csv'), [
            'time', 'server', 'up', 'agent_ok', 'cpu', 'mem', 'sessions', 'active_flows',
            'used_mbps', 'available_mbps', 'rtt_ms', 'loss_pct'])

        kwargs['wsgi'].register(LBRestController, {APP_KEY: self})
        self.logger.info("Service-aware LB: VIP %s, %d servers, mode=%s, config=%s",
                         self.cfg.vip_ip, len(self.servers), self.mode, config_path)
        hub.spawn(self._monitor_loop)

    # ------------------------------------------------------------------
    # Switch connection
    # ------------------------------------------------------------------
    @set_ev_cls(ofp_event.EventOFPSwitchFeatures, CONFIG_DISPATCHER)
    def _switch_features(self, ev):
        dp = ev.msg.datapath
        if self.datapath is not None and self.datapath.id != dp.id:
            self.logger.warning("ignoring extra switch %016x - this app drives a single switch", dp.id)
            return
        self.datapath = dp
        self.flows.install_table_miss(dp)
        self.logger.info("switch %016x connected", dp.id)

    @set_ev_cls(ofp_event.EventOFPStateChange, [MAIN_DISPATCHER, DEAD_DISPATCHER])
    def _state_change(self, ev):
        dp = ev.datapath
        if ev.state == DEAD_DISPATCHER and self.datapath is not None and dp.id == self.datapath.id:
            self.logger.warning("switch %016x disconnected", dp.id)
            self.datapath = None
            self.sticky.clear()
            self.active.clear()
            for s in self.servers:
                s.active_flows = 0

    # ------------------------------------------------------------------
    # Monitoring loop: probes, port stats, agent reports, availability
    # ------------------------------------------------------------------
    def _monitor_loop(self):
        mon = self.cfg.monitoring
        last_stats = last_metrics = last_rebalance = 0.0
        while True:
            try:
                now = time.time()
                dp = self.datapath
                if dp is not None:
                    for s in self.servers:
                        seq = self.net_mon.next_probe(s, now)
                        data = packets.icmp_probe(self.cfg.vip_ip, self.cfg.vip_mac, s,
                                                  NetworkMonitor.PROBE_ID, seq)
                        self.flows.send_raw(dp, s.switch_port, data)
                    if now - last_stats >= mon['port_stats_interval']:
                        self.flows.request_port_stats(dp)
                        last_stats = now
                self.net_mon.expire_probes(now)
                self.srv_mon.refresh(now)
                for s in self.net_mon.update_availability():
                    self._on_availability_change(s)
                if now - last_metrics >= mon['metrics_log_interval']:
                    self._log_metrics(now)
                    last_metrics = now
                self._expire_sticky(now)
                rb = self.cfg.rebalance
                if rb['enabled'] and now - last_rebalance >= rb['interval']:
                    self._rebalance(now)
                    last_rebalance = now
            except Exception:       # keep monitoring alive no matter what
                self.logger.exception("monitor loop error")
            hub.sleep(mon['probe_interval'])

    def _on_availability_change(self, server):
        if server.up:
            self.logger.info("server %s is UP", server.name)
            return
        self.logger.warning("server %s is DOWN - removing its flows", server.name)
        if self.datapath is not None:
            self.flows.delete_server_flows(self.datapath, server.index)
        for key in [k for k, v in self.sticky.items() if v['server'] is server]:
            del self.sticky[key]

    def _rebalance(self, now):
        """Move running UDP flows to a clearly better server (TCP is never moved)."""
        dp = self.datapath
        if dp is None or self.mode == ROUND_ROBIN:
            return
        rb = self.cfg.rebalance
        for cookie, rec in list(self.active.items()):
            client, proto, sport, dport = rec['key']
            if (proto != in_proto.IPPROTO_UDP or rec['service'] not in rb['services']
                    or now - rec['moved_at'] < rb['hold_time']):
                continue
            old = rec['server']
            new = self.engine.better_server(old, rec['service'], self.servers, now, rb['min_gain'])
            if new is None:
                continue
            self._flow_seq += 1
            new_cookie = make_cookie(new.index, self._flow_seq)
            # Same forward match + priority: the switch replaces the old rule in place.
            # The old reverse rule (different match) simply idles out.
            self.flows.install_lb_flows(dp, client, rec['client_mac'], rec['client_port'], new,
                                        proto, sport, dport, new_cookie)
            del self.active[cookie]
            old.active_flows = max(0, old.active_flows - 1)
            new.record_assignment(now, self.cfg.expected_mbps(rec['service']))
            rec.update(server=new, moved_at=now)
            self.active[new_cookie] = rec
            self.sticky[rec['key']] = {'server': new, 'cookie': new_cookie, 'time': now}
            self.migrations += 1
            self._log_decision(now, client, proto, sport, dport, rec['service'], new,
                               'rebalance_from_%s' % old.name, {}, 0.0)

    def _expire_sticky(self, now):
        limit = max(self.cfg.flows['idle_timeout'], 1) * 3
        for key in [k for k, v in self.sticky.items() if now - v['time'] > limit]:
            del self.sticky[key]

    def _log_metrics(self, now):
        window = self.cfg.scoring['pending_window']
        for s in self.servers:
            self.metrics_log.write([
                '%.3f' % now, s.name, int(s.up), int(s.agent_ok), '%.1f' % s.cpu, '%.1f' % s.mem,
                s.sessions(), s.active_flows, '%.2f' % s.used_mbps,
                '%.2f' % s.available_mbps(now, window),
                '' if s.rtt_ms is None else '%.2f' % s.rtt_ms, '%.1f' % (s.loss_rate() * 100)])

    @set_ev_cls(ofp_event.EventOFPPortStatsReply, MAIN_DISPATCHER)
    def _port_stats_reply(self, ev):
        self.net_mon.port_stats(((st.port_no, st.tx_bytes, st.rx_bytes) for st in ev.msg.body),
                                time.time())

    @set_ev_cls(ofp_event.EventOFPFlowRemoved, MAIN_DISPATCHER)
    def _flow_removed(self, ev):
        rec = self.active.pop(ev.msg.cookie, None)
        if rec is None:
            return
        rec['server'].active_flows = max(0, rec['server'].active_flows - 1)
        sticky = self.sticky.get(rec['key'])
        if sticky is not None and sticky['cookie'] == ev.msg.cookie:
            del self.sticky[rec['key']]

    # ------------------------------------------------------------------
    # Packet-in: ARP for the VIP, probe replies, new client flows, plain L2
    # ------------------------------------------------------------------
    @set_ev_cls(ofp_event.EventOFPPacketIn, MAIN_DISPATCHER)
    def _packet_in(self, ev):
        msg = ev.msg
        dp = msg.datapath
        in_port = msg.match['in_port']
        pkt = packet.Packet(msg.data)
        eth = pkt.get_protocol(ethernet.ethernet)
        if eth is None or eth.ethertype in (ether_types.ETH_TYPE_LLDP, ether_types.ETH_TYPE_IPV6):
            return
        self.mac_to_port[eth.src] = in_port

        arp_pkt = pkt.get_protocol(arp.arp)
        if arp_pkt is not None:
            if arp_pkt.opcode == arp.ARP_REQUEST and arp_pkt.dst_ip == self.cfg.vip_ip:
                data = packets.arp_reply(self.cfg.vip_ip, self.cfg.vip_mac, eth, arp_pkt)
                self.flows.send_raw(dp, in_port, data)
                return
            self._l2_forward(msg, in_port, eth)
            return

        ip = pkt.get_protocol(ipv4.ipv4)
        if ip is not None and ip.dst == self.cfg.vip_ip:
            if ip.src in self.server_by_ip:
                self._server_to_vip(pkt, ip)
            else:
                self._client_request(msg, in_port, eth, ip, pkt)
            return
        self._l2_forward(msg, in_port, eth)

    def _server_to_vip(self, pkt, ip):
        ic = pkt.get_protocol(icmp.icmp)
        if ic is not None and ic.type == icmp.ICMP_ECHO_REPLY and isinstance(ic.data, icmp.echo):
            self.net_mon.probe_reply(ip.src, ic.data.id, ic.data.seq, time.time())

    def _client_request(self, msg, in_port, eth, ip, pkt):
        dp = msg.datapath
        src_port = dst_port = None
        if ip.proto == in_proto.IPPROTO_TCP:
            seg = pkt.get_protocol(tcp.tcp)
            src_port, dst_port = seg.src_port, seg.dst_port
        elif ip.proto == in_proto.IPPROTO_UDP:
            seg = pkt.get_protocol(udp.udp)
            src_port, dst_port = seg.src_port, seg.dst_port
        elif ip.proto != in_proto.IPPROTO_ICMP:
            return      # only TCP, UDP and ICMP are load balanced

        now = time.time()
        key = (ip.src, ip.proto, src_port, dst_port)
        sticky = self.sticky.get(key)
        if sticky is not None and sticky['server'].up:
            # More packets of a flow we already placed (sent before its rule was in place).
            server, cookie = sticky['server'], sticky['cookie']
            sticky['time'] = now
        else:
            started = time.perf_counter()
            service = self.classifier.classify(ip.proto, dst_port, ip.tos >> 2)
            server, reason, scores = self.engine.select(self.mode, service, self.servers, now)
            decision_ms = (time.perf_counter() - started) * 1000.0
            self.decision_ms = self.decision_ms[-999:] + [decision_ms]
            self._flow_seq += 1
            cookie = make_cookie(server.index, self._flow_seq)
            server.record_assignment(now, self.cfg.expected_mbps(service))
            self.sticky[key] = {'server': server, 'cookie': cookie, 'time': now}
            self.active[cookie] = {'server': server, 'key': key, 'service': service, 'since': now,
                                   'moved_at': now, 'client_mac': eth.src, 'client_port': in_port}
            self._log_decision(now, ip.src, ip.proto, src_port, dst_port, service, server,
                               reason, scores, decision_ms)

        actions = self.flows.install_lb_flows(dp, ip.src, eth.src, in_port, server,
                                              ip.proto, src_port, dst_port, cookie)
        self.flows.packet_out(dp, msg, actions)

    def _log_decision(self, now, client, proto, sport, dport, service, server, reason, scores,
                      decision_ms):
        self.decision_count += 1
        score_text = ' '.join('%s=%.3f' % kv for kv in sorted(scores.items()))
        proto_name = {6: 'tcp', 17: 'udp', 1: 'icmp'}.get(proto, str(proto))
        self.logger.info("%s %s:%s -> VIP:%s [%s] => %s (%s, %.2f ms) %s", proto_name, client,
                         sport or '-', dport or '-', service, server.name, reason, decision_ms,
                         score_text)
        self.decision_log.write(['%.3f' % now, self.mode, client, proto_name, sport or '',
                                 dport or '', service, server.name, reason,
                                 '%.3f' % decision_ms, score_text])

    def _l2_forward(self, msg, in_port, eth):
        dp = msg.datapath
        ofp, parser = dp.ofproto, dp.ofproto_parser
        out_port = self.mac_to_port.get(eth.dst, ofp.OFPP_FLOOD)
        actions = [parser.OFPActionOutput(out_port)]
        if out_port != ofp.OFPP_FLOOD:
            match = parser.OFPMatch(in_port=in_port, eth_dst=eth.dst, eth_src=eth.src)
            self.flows.add_flow(dp, 1, match, actions, idle=60)
        self.flows.packet_out(dp, msg, actions)

    # ------------------------------------------------------------------
    # Used by the REST API
    # ------------------------------------------------------------------
    def get_status(self):
        now = time.time()
        bw_ref = self.engine.bandwidth_ref(self.servers)
        window = self.cfg.scoring['pending_window']
        servers = []
        for s in self.servers:
            servers.append({
                'name': s.name, 'ip': s.ip, 'switch_port': s.switch_port, 'up': s.up,
                'agent_ok': s.agent_ok, 'cpu': round(s.cpu, 1), 'mem': round(s.mem, 1),
                'sessions': s.sessions(), 'active_flows': s.active_flows,
                'assigned_total': s.assigned_total, 'capacity_mbps': s.capacity_mbps,
                'used_mbps': round(s.used_mbps, 2),
                'available_mbps': round(s.available_mbps(now, window), 2),
                'rtt_ms': None if s.rtt_ms is None else round(s.rtt_ms, 2),
                'loss_pct': round(s.loss_rate() * 100, 1),
                'tx_bytes': s.tx_bytes, 'rx_bytes': s.rx_bytes,
                'port_sample_time': s.last_port_sample[0] if s.last_port_sample else None,
                'services': s.services,
                'scores': {svc: round(self.engine.score(s, svc, now, bw_ref)[0], 3)
                           for svc in self.cfg.services},
            })
        times = sorted(self.decision_ms)
        return {'time': now, 'mode': self.mode, 'vip': self.cfg.vip_ip,
                'switch_connected': self.datapath is not None,
                'decisions': self.decision_count, 'active_flows': len(self.active),
                'decision_ms': {
                    'avg': round(sum(times) / len(times), 3) if times else None,
                    'p95': round(times[int(0.95 * (len(times) - 1))], 3) if times else None,
                    'max': round(times[-1], 3) if times else None},
                'rebalance': dict(self.cfg.rebalance, migrations=self.migrations),
                'weights': {svc: self.engine.weights(svc) for svc in self.cfg.services},
                'servers': servers}

    def get_flows(self):
        out = []
        for cookie, rec in self.active.items():
            client, proto, sport, dport = rec['key']
            out.append({'cookie': hex(cookie), 'client': client, 'proto': proto,
                        'src_port': sport, 'dst_port': dport, 'service': rec['service'],
                        'server': rec['server'].name, 'since': rec['since']})
        return out

    def set_mode(self, mode):
        self.mode = normalise_mode(mode)
        self.logger.info("mode set to %s", self.mode)
        return self.mode

    def set_rebalance(self, enabled):
        if not isinstance(enabled, bool):
            raise ConfigError('"enabled" must be true or false')
        self.cfg.rebalance['enabled'] = enabled
        self.logger.info("live UDP rebalancing %s", 'enabled' if enabled else 'disabled')
        return enabled

    def set_weights(self, service, weights):
        if service not in self.cfg.services:
            raise ConfigError("unknown service %r" % service)
        merged = dict(self.cfg.services[service]['weights'])
        merged.update(weights)
        validate_weights(merged, 'weights for %s' % service)
        self.cfg.services[service]['weights'] = {k: float(merged.get(k, 0)) for k in WEIGHT_KEYS}
        self.logger.info("weights for %s set to %s", service, self.cfg.services[service]['weights'])
        return self.cfg.services[service]['weights']
