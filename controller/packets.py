"""Packets the controller builds itself: ARP replies for the VIP and ICMP latency probes."""
from ryu.lib.packet import arp, ether_types, ethernet, icmp, in_proto, ipv4, packet

PROBE_PAYLOAD = b'sdn-lb-probe'


def arp_reply(vip_ip, vip_mac, request_eth, request_arp):
    pkt = packet.Packet()
    pkt.add_protocol(ethernet.ethernet(dst=request_eth.src, src=vip_mac,
                                       ethertype=ether_types.ETH_TYPE_ARP))
    pkt.add_protocol(arp.arp(opcode=arp.ARP_REPLY, src_mac=vip_mac, src_ip=vip_ip,
                             dst_mac=request_arp.src_mac, dst_ip=request_arp.src_ip))
    pkt.serialize()
    return pkt.data


def icmp_probe(vip_ip, vip_mac, server, ident, seq):
    """Echo request from the VIP to a server; the reply comes back as a PacketIn."""
    pkt = packet.Packet()
    pkt.add_protocol(ethernet.ethernet(dst=server.mac, src=vip_mac,
                                       ethertype=ether_types.ETH_TYPE_IP))
    pkt.add_protocol(ipv4.ipv4(src=vip_ip, dst=server.ip, proto=in_proto.IPPROTO_ICMP, ttl=64))
    pkt.add_protocol(icmp.icmp(type_=icmp.ICMP_ECHO_REQUEST, code=0, csum=0,
                               data=icmp.echo(id_=ident, seq=seq, data=PROBE_PAYLOAD)))
    pkt.serialize()
    return pkt.data
