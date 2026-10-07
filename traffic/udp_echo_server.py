#!/usr/bin/env python3
"""UDP echo server: sends every datagram straight back. Used for VoIP and video tests."""
import argparse
import selectors
import socket


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--ports', type=int, nargs='+', required=True)
    args = ap.parse_args()

    sel = selectors.DefaultSelector()
    for port in args.ports:
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_RCVBUF, 4 * 1024 * 1024)
        sock.bind(('0.0.0.0', port))
        sock.setblocking(False)
        sel.register(sock, selectors.EVENT_READ)

    while True:
        for key, _ in sel.select():
            sock = key.fileobj
            while True:
                try:
                    data, addr = sock.recvfrom(65535)
                except BlockingIOError:
                    break
                try:
                    sock.sendto(data, addr)
                except OSError:
                    pass


if __name__ == '__main__':
    main()
