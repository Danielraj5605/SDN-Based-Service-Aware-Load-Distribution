#!/usr/bin/env python3
"""Server telemetry agent - runs on every backend server (one per Mininet host).

Every --interval seconds it writes <dir>/<name>.json with:
    cpu       % CPU used by processes in this host's network namespace
    mem       % memory used by those processes
    sessions  established TCP connections on this host

Mininet hosts share one kernel, so system-wide CPU would be the same for every
server. Counting only the processes in this host's network namespace gives a
real per-server value. --extra-cpu / --extra-mem add a fixed offset so a
"busy" server can be emulated.
"""
import argparse
import json
import os
import time

import psutil


def netns_of(pid='self'):
    try:
        return os.readlink('/proc/%s/ns/net' % pid)
    except OSError:
        return None


class NamespaceUsage:
    """CPU and memory of every process that shares our network namespace."""

    def __init__(self):
        self.netns = netns_of()
        self.procs = {}
        self.ncpu = psutil.cpu_count() or 1

    def sample(self):
        cpu = mem = 0.0
        seen = set()
        for pid in psutil.pids():
            if netns_of(pid) != self.netns:
                continue
            seen.add(pid)
            proc = self.procs.get(pid)
            try:
                if proc is None:
                    proc = self.procs[pid] = psutil.Process(pid)
                    proc.cpu_percent(None)      # first call only primes the counter
                    continue
                cpu += proc.cpu_percent(None)
                mem += proc.memory_percent()
            except psutil.Error:
                self.procs.pop(pid, None)
        for pid in list(self.procs):
            if pid not in seen:
                del self.procs[pid]
        return cpu / self.ncpu, mem


def tcp_sessions():
    # /proc/net/tcp is per network namespace, so this only sees this host's sockets.
    return sum(1 for c in psutil.net_connections(kind='tcp')
               if c.status == psutil.CONN_ESTABLISHED and c.raddr)


def write_atomic(path, data):
    tmp = path + '.tmp'
    with open(tmp, 'w') as f:
        json.dump(data, f)
    os.replace(tmp, path)


def main():
    ap = argparse.ArgumentParser(description=__doc__.split('\n')[0])
    ap.add_argument('--name', required=True, help='server name, e.g. srv1')
    ap.add_argument('--dir', default='/tmp/sdn_lb/stats', help='shared stats directory')
    ap.add_argument('--interval', type=float, default=1.0)
    ap.add_argument('--extra-cpu', type=float, default=0.0, help='%% CPU added to emulate load')
    ap.add_argument('--extra-mem', type=float, default=0.0, help='%% memory added to emulate load')
    args = ap.parse_args()

    os.makedirs(args.dir, exist_ok=True)
    path = os.path.join(args.dir, args.name + '.json')
    usage = NamespaceUsage()
    while True:
        cpu, mem = usage.sample()
        write_atomic(path, {
            'name': args.name,
            'ts': time.time(),
            'cpu': round(min(100.0, cpu + args.extra_cpu), 2),
            'mem': round(min(100.0, mem + args.extra_mem), 2),
            'sessions': tcp_sessions(),
        })
        time.sleep(args.interval)


if __name__ == '__main__':
    main()
