#!/usr/bin/env python3
"""Call-quality compliance report from existing results/flows_*.csv files.

Reads the latest flow CSV files and computes:
  - VoIP:  % calls PASS = RTT <= 150 ms AND jitter <= 30 ms AND loss <= 1%
  - Video: % streams PASS = RTT <= 150 ms AND loss <= 5%
  - File:  mean throughput and % of transfers above 80 Mbit/s

Includes:
  - "Why Round Robin fails" failure mode breakdown (delay vs loss-only)
  - Delay-only view (RTT <= 150 ms only)
  - RTT sensitivity table (RTT <= 100 / 150 / 300 ms, fixed a priori)
  - Loss sensitivity table (loss <= 1% / 3% / 5%, added after seeing results, for transparency)

Usage (no sudo needed):
    python3 experiments/quality_report.py
    python3 experiments/quality_report.py --files results/flows_X.csv
"""
import argparse
import csv
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
RESULTS_DIR = os.path.join(ROOT, 'results')

MODES = ['round_robin', 'service_aware', 'service_aware_rebalance']
MODE_LABELS = {
    'round_robin':              'Round Robin',
    'service_aware':            'Service-Aware',
    'service_aware_rebalance':  'SA + Rebalance',
}

# ---- Thresholds (commonly used VoIP quality targets chosen before experiments were run) ----
VOIP_RTT_DEFAULT_MS = 150      # primary
VOIP_RTT_STRICT_MS  = 100      # sensitivity low
VOIP_RTT_RELAXED_MS = 300      # sensitivity high
VOIP_JITTER_MS      = 30
VOIP_LOSS_PCT       = 1.0

VIDEO_RTT_MS        = 150
VIDEO_LOSS_PCT      = 5.0

FILE_TPUT_MIN_MBPS  = 80.0


def load_flows(paths):
    rows = []
    for p in paths:
        with open(p, newline='', encoding='utf-8') as f:
            reader = csv.DictReader(f)
            for row in reader:
                for k in ('throughput_mbps', 'rtt_avg_ms', 'rtt_p95_ms',
                          'jitter_ms', 'loss_pct'):
                    raw = row.get(k, '')
                    row[k] = float(raw) if raw not in ('', None) else None
                rows.append(row)
    return rows


def val(row, key):
    return row.get(key)


def _voip_pass(row, rtt_limit=VOIP_RTT_DEFAULT_MS, loss_limit=VOIP_LOSS_PCT):
    rtt = val(row, 'rtt_avg_ms')
    jit = val(row, 'jitter_ms')
    los = val(row, 'loss_pct')
    if rtt is None or jit is None or los is None:
        return None
    return rtt <= rtt_limit and jit <= VOIP_JITTER_MS and los <= loss_limit


def _video_pass(row):
    rtt = val(row, 'rtt_avg_ms')
    los = val(row, 'loss_pct')
    if rtt is None or los is None:
        return None
    return rtt <= VIDEO_RTT_MS and los <= VIDEO_LOSS_PCT


def pass_rate(results):
    judged = [r for r in results if r is not None]
    if not judged:
        return 0, 0, None
    passed = sum(judged)
    return passed, len(judged), 100.0 * passed / len(judged)


def compute_quality(rows, modes, rtt_limit=VOIP_RTT_DEFAULT_MS):
    out = {}
    for mode in modes:
        mode_rows = [r for r in rows if r['mode'] == mode]

        voip_rows  = [r for r in mode_rows if r['service'] == 'voip']
        video_rows = [r for r in mode_rows if r['service'] == 'video']
        file_rows  = [r for r in mode_rows if r['service'] == 'file']

        vp = [_voip_pass(r, rtt_limit, VOIP_LOSS_PCT) for r in voip_rows]
        vp_n, vp_tot, vp_pct = pass_rate(vp)

        # Delay-only view
        vp_delay = [val(r, 'rtt_avg_ms') is not None and val(r, 'rtt_avg_ms') <= rtt_limit for r in voip_rows]
        vpd_n, vpd_tot, vpd_pct = pass_rate(vp_delay)

        # Failure breakdown
        fail_delay = 0
        fail_loss_only = 0
        for r in voip_rows:
            rtt, jit, los = val(r, 'rtt_avg_ms'), val(r, 'jitter_ms'), val(r, 'loss_pct')
            if None not in (rtt, jit, los):
                if rtt > rtt_limit:
                    fail_delay += 1
                elif rtt <= rtt_limit and jit <= VOIP_JITTER_MS and los > VOIP_LOSS_PCT:
                    fail_loss_only += 1

        vid_p = [_video_pass(r) for r in video_rows]
        vid_n, vid_tot, vid_pct = pass_rate(vid_p)

        tputs = [val(r, 'throughput_mbps') for r in file_rows if val(r, 'throughput_mbps') is not None]
        file_mean = sum(tputs) / len(tputs) if tputs else None
        file_hi   = sum(1 for t in tputs if t >= FILE_TPUT_MIN_MBPS)
        file_hi_pct = 100.0 * file_hi / len(tputs) if tputs else None

        voip_rtts = [val(r, 'rtt_avg_ms') for r in voip_rows if val(r, 'rtt_avg_ms') is not None]
        voip_mean_rtt = sum(voip_rtts) / len(voip_rtts) if voip_rtts else None

        out[mode] = {
            'voip_pass_n':       vp_n,
            'voip_total':        vp_tot,
            'voip_pass_pct':     vp_pct,
            'voip_delay_pass_n': vpd_n,
            'voip_delay_pct':    vpd_pct,
            'fail_delay':        fail_delay,
            'fail_loss_only':    fail_loss_only,
            'voip_mean_rtt':     voip_mean_rtt,
            'video_pass_n':      vid_n,
            'video_total':       vid_tot,
            'video_pass_pct':    vid_pct,
            'file_mean_mbps':    file_mean,
            'file_hi_pct':       file_hi_pct,
            'file_total':        len(file_rows),
        }
    return out


def fmt_pct(n, tot, pct):
    if tot == 0:
        return '-'
    if pct is None:
        return '-'
    return '%d/%d (%.0f%%)' % (n, tot, pct)


def fmt_mbps(v):
    return '-' if v is None else '%.1f' % v


def print_quality_table(label, quality, modes):
    hdr = '%-44s' % ('  ' + label) + ''.join('%20s' % MODE_LABELS.get(m, m) for m in modes)
    print(hdr)
    print('-' * (44 + 20 * len(modes)))

    voip_vals = [(quality[m]['voip_pass_n'],
                  quality[m]['voip_total'],
                  quality[m]['voip_pass_pct']) for m in modes]
    voip_delay_vals = [(quality[m]['voip_delay_pass_n'],
                        quality[m]['voip_total'],
                        quality[m]['voip_delay_pct']) for m in modes]
    vid_vals  = [(quality[m]['video_pass_n'],
                  quality[m]['video_total'],
                  quality[m]['video_pass_pct']) for m in modes]
    file_vals = [(quality[m]['file_mean_mbps'], quality[m]['file_hi_pct'],
                  quality[m]['file_total']) for m in modes]

    print('%-44s' % '  VoIP PASS = RTT<=150ms AND jit<=30ms AND loss<=1%'
          + ''.join('%20s' % fmt_pct(*v) for v in voip_vals))
    print('%-44s' % '  VoIP delay-only view (RTT <= 150 ms only)'
          + ''.join('%20s' % fmt_pct(*v) for v in voip_delay_vals))
    print('%-44s' % '    -- failed on delay (RTT > 150 ms)'
          + ''.join('%20s' % ('%d calls' % quality[m]['fail_delay']) for m in modes))
    print('%-44s' % '    -- failed on loss only (loss > 1%, srv4)'
          + ''.join('%20s' % ('%d calls' % quality[m]['fail_loss_only']) for m in modes))
    print('%-44s' % '  VoIP mean RTT (ms)'
          + ''.join('%20s' % fmt_mbps(quality[m]['voip_mean_rtt']) for m in modes))
    print('%-44s' % '  Video streams PASS (RTT <= 150 ms, loss <= 5%)'
          + ''.join('%20s' % fmt_pct(*v) for v in vid_vals))
    print('%-44s' % '  File mean throughput (Mbit/s)'
          + ''.join('%20s' % fmt_mbps(v[0]) for v in file_vals))
    print('%-44s' % ('  File > %.0f Mbit/s' % FILE_TPUT_MIN_MBPS)
          + ''.join('%20s' % ('-' if v[1] is None else '%.0f%% (%d)' % (v[1], v[2]))
                    for v in file_vals))
    print()


def print_sensitivity_tables(rows, modes):
    print('VoIP RTT sensitivity table (chosen before experiments were run):')
    print('%-26s' % 'RTT limit (ms)'
          + ''.join('%20s' % MODE_LABELS.get(m, m) for m in modes))
    print('-' * (26 + 20 * len(modes)))
    for rtt_lim in [VOIP_RTT_STRICT_MS, VOIP_RTT_DEFAULT_MS, VOIP_RTT_RELAXED_MS]:
        q = compute_quality(rows, modes, rtt_limit=rtt_lim)
        print('%-26s' % ('  <= %d ms (jit<=30, loss<=1%%)' % rtt_lim)
              + ''.join('%20s' % fmt_pct(q[m]['voip_pass_n'],
                                         q[m]['voip_total'],
                                         q[m]['voip_pass_pct'])
                        for m in modes))
    print()

    print('VoIP Loss sensitivity table (added after seeing results, shown for transparency):')
    print('%-26s' % 'Loss limit (%)'
          + ''.join('%20s' % MODE_LABELS.get(m, m) for m in modes))
    print('-' * (26 + 20 * len(modes)))
    for loss_lim in [1.0, 3.0, 5.0]:
        res_per_mode = []
        for m in modes:
            m_rows = [r for r in rows if r['mode'] == m and r['service'] == 'voip']
            p = sum(1 for r in m_rows if _voip_pass(r, VOIP_RTT_DEFAULT_MS, loss_lim))
            tot = len(m_rows)
            pct = (100.0 * p / tot) if tot else 0.0
            res_per_mode.append((p, tot, pct))
        print('%-26s' % ('  <= %.0f%% (RTT<=150ms, jit<=30)' % loss_lim)
              + ''.join('%20s' % fmt_pct(*v) for v in res_per_mode))
    print()


def write_csv_report(rows, modes, tag, rtt_limit=VOIP_RTT_DEFAULT_MS):
    q = compute_quality(rows, modes, rtt_limit)
    out_rows = []
    for m in modes:
        d = q[m]
        out_rows.append({
            'mode': m,
            'voip_pass_n': d['voip_pass_n'],
            'voip_total': d['voip_total'],
            'voip_pass_pct': '' if d['voip_pass_pct'] is None else '%.1f' % d['voip_pass_pct'],
            'voip_delay_pass_n': d['voip_delay_pass_n'],
            'voip_delay_pct': '' if d['voip_delay_pct'] is None else '%.1f' % d['voip_delay_pct'],
            'fail_delay': d['fail_delay'],
            'fail_loss_only': d['fail_loss_only'],
            'voip_mean_rtt_ms': '' if d['voip_mean_rtt'] is None else '%.2f' % d['voip_mean_rtt'],
            'video_pass_n': d['video_pass_n'],
            'video_total': d['video_total'],
            'video_pass_pct': '' if d['video_pass_pct'] is None else '%.1f' % d['video_pass_pct'],
            'file_mean_mbps': '' if d['file_mean_mbps'] is None else '%.2f' % d['file_mean_mbps'],
            'file_above_80_pct': '' if d['file_hi_pct'] is None else '%.1f' % d['file_hi_pct'],
            'voip_rtt_limit_ms': rtt_limit,
            'voip_jitter_limit_ms': VOIP_JITTER_MS,
            'voip_loss_limit_pct': VOIP_LOSS_PCT,
            'video_rtt_limit_ms': VIDEO_RTT_MS,
            'video_loss_limit_pct': VIDEO_LOSS_PCT,
        })
    fields = ['mode', 'voip_pass_n', 'voip_total', 'voip_pass_pct',
              'voip_delay_pass_n', 'voip_delay_pct', 'fail_delay', 'fail_loss_only',
              'voip_mean_rtt_ms', 'video_pass_n', 'video_total', 'video_pass_pct',
              'file_mean_mbps', 'file_above_80_pct',
              'voip_rtt_limit_ms', 'voip_jitter_limit_ms', 'voip_loss_limit_pct',
              'video_rtt_limit_ms', 'video_loss_limit_pct']
    path = os.path.join(RESULTS_DIR, 'quality_%s.csv' % tag)
    with open(path, 'w', newline='', encoding='utf-8') as f:
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        w.writerows(out_rows)
    return path


def find_latest_flows(n=2):
    files = sorted(
        [os.path.join(RESULTS_DIR, f) for f in os.listdir(RESULTS_DIR)
         if f.startswith('flows_') and f.endswith('.csv')],
        reverse=True
    )
    return files[:n]


def main():
    ap = argparse.ArgumentParser(description='Call-quality compliance report')
    ap.add_argument('--files', nargs='+', default=None,
                    help='CSV file(s) to analyse (default: latest 2 in results/)')
    args = ap.parse_args()

    files = args.files if args.files else find_latest_flows(2)
    if not files:
        sys.exit('No flow CSV files found in results/. Run experiments/run_experiment.py first.')

    print('\n=== Call-Quality Compliance Report ===')
    print('Criteria (commonly used VoIP quality targets chosen before experiments were run):')
    print('  VoIP PASS = RTT <= %d ms AND jitter <= %d ms AND loss <= %.0f%%'
          % (VOIP_RTT_DEFAULT_MS, VOIP_JITTER_MS, VOIP_LOSS_PCT))
    print('  Video PASS = RTT <= %d ms AND loss <= %.0f%%' % (VIDEO_RTT_MS, VIDEO_LOSS_PCT))
    print('  File "good" = throughput >= %.0f Mbit/s' % FILE_TPUT_MIN_MBPS)
    print()

    all_tags = []
    for fpath in files:
        rows = load_flows([fpath])
        modes_present = sorted({r['mode'] for r in rows},
                               key=lambda m: MODES.index(m) if m in MODES else 99)
        tag = os.path.basename(fpath).replace('flows_', '').replace('.csv', '')
        all_tags.append(tag)
        print('--- File: %s ---' % os.path.basename(fpath))
        q = compute_quality(rows, modes_present)
        print_quality_table(
            'Quality metrics (Primary: RTT <= %d ms)' % VOIP_RTT_DEFAULT_MS,
            q, modes_present)
        print_sensitivity_tables(rows, modes_present)

        csv_path = write_csv_report(rows, modes_present, tag)
        print('  -> CSV written: %s' % csv_path)
        print()

    print('Done.')


if __name__ == '__main__':
    main()
