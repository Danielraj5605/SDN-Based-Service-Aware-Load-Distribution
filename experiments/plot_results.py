#!/usr/bin/env python3
"""Plots Round Robin vs Service-Aware from the CSVs written by run_experiment.py.

    python3 experiments/plot_results.py                 (latest run)
    python3 experiments/plot_results.py --tag 20261007-153000

Writes results/plots/comparison_<tag>.png, results/plots/servers_<tag>.png and
results/summary_<tag>.csv (the numbers behind the charts).
"""
import argparse
import glob
import os

import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt      # noqa: E402
import pandas as pd                  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
RESULTS = os.path.join(ROOT, 'results')

# Colour follows the mode, never its position: blue = Round Robin, orange = Service-Aware,
# aqua = Service-Aware with live rebalancing.
MODE_COLORS = {'round_robin': '#2a78d6', 'service_aware': '#eb6834',
               'service_aware_rebalance': '#1baf7a'}
MODE_LABELS = {'round_robin': 'Round Robin', 'service_aware': 'Service-Aware',
               'service_aware_rebalance': 'SA + rebalance'}
INK, INK_MUTED, GRID, SURFACE = '#0b0b0b', '#52514e', '#e4e3df', '#fcfcfb'

PANELS = [   # (service, column, title, lower is better)
    ('voip', 'rtt_avg_ms', 'VoIP round-trip latency (ms)', True),
    ('voip', 'jitter_ms', 'VoIP jitter (ms)', True),
    ('voip', 'loss_pct', 'VoIP packet loss (%)', True),
    ('video', 'throughput_mbps', 'Video delivered throughput (Mbit/s)', False),
    ('video', 'loss_pct', 'Video packet loss (%)', True),
    ('file', 'throughput_mbps', 'File transfer throughput (Mbit/s)', False),
]


def latest_tag():
    files = sorted(glob.glob(os.path.join(RESULTS, 'flows_*.csv')))
    if not files:
        raise SystemExit('no results/flows_*.csv found - run experiments/run_experiment.py first')
    return os.path.basename(files[-1])[len('flows_'):-len('.csv')]


def style_axis(ax, title):
    ax.set_facecolor(SURFACE)
    ax.set_title(title, fontsize=10, color=INK, loc='left')
    ax.grid(axis='y', color=GRID, linewidth=0.8)
    ax.set_axisbelow(True)
    for side in ('top', 'right', 'left'):
        ax.spines[side].set_visible(False)
    ax.spines['bottom'].set_color(INK_MUTED)
    ax.tick_params(colors=INK_MUTED, labelsize=9, length=0)


def bar_panel(ax, modes, means, stds, title, lower_better):
    xs = range(len(modes))
    bars = ax.bar(xs, means, width=0.55, color=[MODE_COLORS.get(m, '#888888') for m in modes],
                  yerr=stds, error_kw={'ecolor': INK_MUTED, 'elinewidth': 1, 'capsize': 3},
                  edgecolor=SURFACE, linewidth=2)
    ax.set_xticks(list(xs))
    ax.set_xticklabels([MODE_LABELS.get(m, m) for m in modes])
    style_axis(ax, title + ('  ↓ better' if lower_better else '  ↑ better'))
    top = max([m + (s or 0) for m, s in zip(means, stds)] + [1e-9])
    ax.set_ylim(0, top * 1.25)
    for bar, value, std in zip(bars, means, stds):
        # Label sits above the error bar so the two never overlap.
        ax.text(bar.get_x() + bar.get_width() / 2, value + (std or 0) + top * 0.03,
                '%.2f' % value, ha='center', va='bottom', fontsize=9, color=INK)


def main():
    ap = argparse.ArgumentParser(description=__doc__.split('\n')[0])
    ap.add_argument('--tag', help='timestamp tag of the run (default: latest)')
    args = ap.parse_args()
    tag = args.tag or latest_tag()

    flows = pd.read_csv(os.path.join(RESULTS, 'flows_%s.csv' % tag))
    rounds = pd.read_csv(os.path.join(RESULTS, 'rounds_%s.csv' % tag))
    modes = [m for m in MODE_COLORS if m in set(flows['mode'])] + \
            sorted(set(flows['mode']) - set(MODE_COLORS))
    out_dir = os.path.join(RESULTS, 'plots')
    os.makedirs(out_dir, exist_ok=True)

    # ---- Figure 1: QoS metrics + fairness, one panel per metric (one axis each) ----
    fig, axes = plt.subplots(3, 3, figsize=(13, 10), facecolor=SURFACE)
    axes = axes.flatten()
    summary = []
    for ax, (service, col, title, lower) in zip(axes, PANELS):
        sub = flows[flows['service'] == service]
        means = [sub[sub['mode'] == m][col].mean() for m in modes]
        stds = [sub[sub['mode'] == m][col].std() for m in modes]
        means = [0.0 if pd.isna(v) else v for v in means]
        stds = [0.0 if pd.isna(v) else v for v in stds]
        bar_panel(ax, modes, means, stds, title, lower)
        summary += [{'metric': title, 'mode': m, 'mean': mu, 'std': sd}
                    for m, mu, sd in zip(modes, means, stds)]

    means = [rounds[rounds['mode'] == m]['fairness'].mean() for m in modes]
    stds = [rounds[rounds['mode'] == m]['fairness'].std() for m in modes]
    means = [0.0 if pd.isna(v) else v for v in means]
    stds = [0.0 if pd.isna(v) else v for v in stds]
    bar_panel(axes[6], modes, means, stds, "Jain's fairness of server utilisation", False)
    axes[6].set_ylim(0, 1.15)
    summary += [{'metric': "Jain's fairness", 'mode': m, 'mean': mu, 'std': sd}
                for m, mu, sd in zip(modes, means, stds)]
    for ax in axes[7:]:
        ax.axis('off')

    handles = [plt.Rectangle((0, 0), 1, 1, color=MODE_COLORS.get(m, '#888888')) for m in modes]
    fig.legend(handles, [MODE_LABELS.get(m, m) for m in modes], loc='upper right',
               frameon=False, fontsize=10)
    fig.suptitle('Round Robin vs Service-Aware load distribution  (mean ± std, run %s)' % tag,
                 x=0.02, ha='left', fontsize=12, color=INK)
    fig.tight_layout(rect=(0, 0, 1, 0.95))
    path1 = os.path.join(out_dir, 'comparison_%s.png' % tag)
    fig.savefig(path1, dpi=150, facecolor=SURFACE)
    plt.close(fig)

    # ---- Figure 2: where traffic went - utilisation and flow count per server ----
    servers = sorted(c[len('util_'):] for c in rounds.columns if c.startswith('util_'))
    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(13, 4.5), facecolor=SURFACE)
    width = 0.8 / max(1, len(modes))
    for i, m in enumerate(modes):
        sub = rounds[rounds['mode'] == m]
        xs = [j + (i - (len(modes) - 1) / 2) * width for j in range(len(servers))]
        util = [sub['util_%s' % s].mean() * 100 for s in servers]
        count = [sub['flows_%s' % s].mean() for s in servers]
        for ax, values in ((ax1, util), (ax2, count)):
            ax.bar(xs, values, width=width, color=MODE_COLORS.get(m, '#888888'),
                   edgecolor=SURFACE, linewidth=2, label=MODE_LABELS.get(m, m))
    for ax, title in ((ax1, 'Link utilisation per server (%)'),
                      (ax2, 'Flows assigned per server (per round)')):
        ax.set_xticks(range(len(servers)))
        ax.set_xticklabels(servers)
        style_axis(ax, title)
    fig.legend(handles, [MODE_LABELS.get(m, m) for m in modes], loc='upper right',
               ncol=len(modes), frameon=False, fontsize=10)
    fig.tight_layout(rect=(0, 0, 1, 0.92))
    path2 = os.path.join(out_dir, 'servers_%s.png' % tag)
    fig.savefig(path2, dpi=150, facecolor=SURFACE)
    plt.close(fig)

    path3 = os.path.join(RESULTS, 'summary_%s.csv' % tag)
    pd.DataFrame(summary).to_csv(path3, index=False)
    print('wrote\n  %s\n  %s\n  %s' % (path1, path2, path3))


if __name__ == '__main__':
    main()
