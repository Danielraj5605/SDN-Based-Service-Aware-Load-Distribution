"""Flow Manager: everything that sends OpenFlow 1.3 messages to the switch."""
from ryu.lib.packet import in_proto

COOKIE_SERVER_MASK = 0xFFFFFFFF00000000


def make_cookie(server_index, flow_seq):
    """High 32 bits = server, low 32 bits = flow; lets us delete all flows of one server."""
    return (server_index << 32) | (flow_seq & 0xFFFFFFFF)


class FlowManager:
    def __init__(self, cfg):
        self.vip_ip = cfg.vip_ip
        self.vip_mac = cfg.vip_mac
        self.priority = int(cfg.flows['priority'])
        self.idle_timeout = int(cfg.flows['idle_timeout'])
        self.hard_timeout = int(cfg.flows['hard_timeout'])

    @staticmethod
    def add_flow(dp, priority, match, actions, idle=0, hard=0, cookie=0, flags=0):
        ofp, parser = dp.ofproto, dp.ofproto_parser
        inst = [parser.OFPInstructionActions(ofp.OFPIT_APPLY_ACTIONS, actions)]
        dp.send_msg(parser.OFPFlowMod(
            datapath=dp, cookie=cookie, priority=priority, match=match, instructions=inst,
            idle_timeout=idle, hard_timeout=hard, flags=flags))

    def install_table_miss(self, dp):
        ofp, parser = dp.ofproto, dp.ofproto_parser
        actions = [parser.OFPActionOutput(ofp.OFPP_CONTROLLER, ofp.OFPCML_NO_BUFFER)]
        self.add_flow(dp, 0, parser.OFPMatch(), actions)

    def install_lb_flows(self, dp, client_ip, client_mac, client_port,
                         server, ip_proto, src_port, dst_port, cookie):
        """Install client->VIP (rewritten to server) and server->client (rewritten to VIP).

        Returns the forward actions so the caller can apply them to the first packet.
        """
        parser = dp.ofproto_parser
        fwd = dict(in_port=client_port, eth_type=0x0800, ip_proto=ip_proto,
                   ipv4_src=client_ip, ipv4_dst=self.vip_ip)
        rev = dict(in_port=server.switch_port, eth_type=0x0800, ip_proto=ip_proto,
                   ipv4_src=server.ip, ipv4_dst=client_ip)
        if ip_proto == in_proto.IPPROTO_TCP:
            fwd.update(tcp_src=src_port, tcp_dst=dst_port)
            rev.update(tcp_src=dst_port, tcp_dst=src_port)
        elif ip_proto == in_proto.IPPROTO_UDP:
            fwd.update(udp_src=src_port, udp_dst=dst_port)
            rev.update(udp_src=dst_port, udp_dst=src_port)

        fwd_actions = [parser.OFPActionSetField(eth_dst=server.mac),
                       parser.OFPActionSetField(ipv4_dst=server.ip),
                       parser.OFPActionOutput(server.switch_port)]
        rev_actions = [parser.OFPActionSetField(eth_src=self.vip_mac),
                       parser.OFPActionSetField(ipv4_src=self.vip_ip),
                       parser.OFPActionSetField(eth_dst=client_mac),
                       parser.OFPActionOutput(client_port)]

        # Reverse first, so the server's first reply already has a rule waiting.
        self.add_flow(dp, self.priority, parser.OFPMatch(**rev), rev_actions,
                      self.idle_timeout, self.hard_timeout, cookie)
        # Only the forward rule reports its removal; that is how active flows are counted.
        self.add_flow(dp, self.priority, parser.OFPMatch(**fwd), fwd_actions,
                      self.idle_timeout, self.hard_timeout, cookie,
                      flags=dp.ofproto.OFPFF_SEND_FLOW_REM)
        return fwd_actions

    def delete_server_flows(self, dp, server_index):
        ofp, parser = dp.ofproto, dp.ofproto_parser
        dp.send_msg(parser.OFPFlowMod(
            datapath=dp, cookie=server_index << 32, cookie_mask=COOKIE_SERVER_MASK,
            table_id=ofp.OFPTT_ALL, command=ofp.OFPFC_DELETE,
            out_port=ofp.OFPP_ANY, out_group=ofp.OFPG_ANY, match=parser.OFPMatch()))

    @staticmethod
    def packet_out(dp, msg, actions):
        """Send the packet that caused a PacketIn using `actions`."""
        ofp, parser = dp.ofproto, dp.ofproto_parser
        data = msg.data if msg.buffer_id == ofp.OFP_NO_BUFFER else None
        dp.send_msg(parser.OFPPacketOut(datapath=dp, buffer_id=msg.buffer_id,
                                        in_port=msg.match['in_port'],
                                        actions=actions, data=data))

    @staticmethod
    def send_raw(dp, out_port, data):
        """Inject a controller-built packet out of `out_port`."""
        ofp, parser = dp.ofproto, dp.ofproto_parser
        dp.send_msg(parser.OFPPacketOut(datapath=dp, buffer_id=ofp.OFP_NO_BUFFER,
                                        in_port=ofp.OFPP_CONTROLLER,
                                        actions=[parser.OFPActionOutput(out_port)],
                                        data=data))

    @staticmethod
    def request_port_stats(dp):
        ofp, parser = dp.ofproto, dp.ofproto_parser
        dp.send_msg(parser.OFPPortStatsRequest(dp, 0, ofp.OFPP_ANY))
