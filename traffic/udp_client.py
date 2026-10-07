#!/usr/bin/env python3
"""Paced UDP client for the echo server; prints one JSON line of results.

    VoIP-like : --rate 50  --size 160   (G.711, 20 ms packets, ~64 kbit/s)
    video-like: --rate 500 --size 1000  (~4 Mbit/s)

Reports round-trip latency (avg / p50 / p95 / max), jitter (mean change in RTT
between consecutive packets), packet loss and delivered throughput.
"""
import argparse
import json
import socket
import struct
import threading
import time

HEADER = struct.Struct('!Id')     # sequence number, send time


def percentile(sorted_values, pct):
    if not sorted_values:
        return None
    idx = min(len(sorted_values) - 1, int(round(pct / 100.0 * (len(sorted_values) - 1))))
    return sorted_values[idx]


def main():
    ap = argparse.ArgumentParser(description=__doc__.split('\n')[0])
    ap.add_argument('--host', required=True)
    ap.add_argument('--port', type=int, required=True)
    ap.add_argument('--rate', type=float, default=50, help='packets per second')
    ap.add_argument('--size', type=int, default=160, help='payload bytes')
    ap.add_argument('--duration', type=float, default=10)
    ap.add_argument('--wait', type=float, default=1.0, help='seconds to wait for late replies')
    ap.add_argument('--dscp', type=int, default=0, help='DSCP mark, e.g. 46 = EF (voice)')
    args = ap.parse_args()

    size = max(args.size, HEADER.size)
    padding = b'\0' * (size - HEADER.size)
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    if args.dscp:
        sock.setsockopt(socket.IPPROTO_IP, socket.IP_TOS, args.dscp << 2)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_RCVBUF, 4 * 1024 * 1024)
    sock.connect((args.host, args.port))
    sock.settimeout(0.2)

    rtts = {}
    stop = threading.Event()

    def receiver():
        while not stop.is_set():
            try:
                data = sock.recv(65535)
            except socket.timeout:
                continue
            except OSError:
                continue
            if len(data) >= HEADER.size:
                seq, sent_at = HEADER.unpack_from(data)
                rtts.setdefault(seq, (time.monotonic() - sent_at) * 1000.0)

    thread = threading.Thread(target=receiver, daemon=True)
    thread.start()

    interval = 1.0 / args.rate
    start = time.monotonic()
    end = start + args.duration
    next_send = start
    sent = 0
    while True:
        now = time.monotonic()
        if now >= end:
            break
        if now < next_send:
            time.sleep(min(next_send - now, 0.005))
            continue
        try:
            sock.send(HEADER.pack(sent, time.monotonic()) + padding)
        except OSError:
            pass                        # e.g. ICMP unreachable reported on the socket
        sent += 1
        next_send += interval

    time.sleep(args.wait)
    stop.set()
    thread.join()

    ordered = [rtts[s] for s in sorted(rtts)]
    values = sorted(ordered)
    jitter = (sum(abs(b - a) for a, b in zip(ordered, ordered[1:])) / (len(ordered) - 1)
              if len(ordered) > 1 else None)
    received = len(rtts)

    def r(x):
        return None if x is None else round(x, 3)

    print(json.dumps({
        'sent': sent,
        'received': received,
        'loss_pct': round(100.0 * (1 - received / sent), 2) if sent else None,
        'rtt_avg_ms': r(sum(values) / len(values)) if values else None,
        'rtt_p50_ms': r(percentile(values, 50)),
        'rtt_p95_ms': r(percentile(values, 95)),
        'rtt_max_ms': r(values[-1]) if values else None,
        'jitter_ms': r(jitter),
        'throughput_mbps': round(received * size * 8 / args.duration / 1e6, 3),
    }))


if __name__ == '__main__':
    main()
