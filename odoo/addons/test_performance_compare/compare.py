#!/usr/bin/env python3
"""Compare two ``test_performance_compare`` result files.

Pure standard library — runs under any Python 3, no Odoo import — so it can diff
a fork run against an upstream run regardless of which interpreter produced each.

Usage::

    python3 compare.py BASELINE.json CANDIDATE.json [--md] [--metric median|mean|p95]

By convention BASELINE is upstream and CANDIDATE is the fork, so a *speedup > 1*
means the fork is faster.  Timing is the headline; query counts are a guardrail —
any benchmark whose query count differs between the two builds is flagged, because
a Python-time win that quietly adds SQL round-trips is not a real win.
"""

# ruff: noqa: T201  (this is a CLI; print() is the user-facing output)
import argparse
import json
import math
import statistics
import sys
from pathlib import Path

METRIC_KEY = {"median": "median_us", "mean": "mean_us", "p95": "p95_us"}

# A speedup outside [1/THRESHOLD, THRESHOLD] is considered a real move rather
# than noise; anything inside is reported as "~".
THRESHOLD = 1.05

# Cross-run coefficient of variation above this means the benchmark is noisy
# *between* process launches (typical for DB-bound ops) and its speedup should
# be read as indicative only.
NOISY_CV = 0.15


def _load(path):
    with Path(path).open() as fh:
        data = json.load(fh)
    if "results" not in data or "meta" not in data:
        sys.exit(f"{path}: not a perf_compare report")
    return data


def _aggregate(paths, metric_key):
    """Load one or more reports for a side and reduce to per-benchmark stats.

    Returns ``(meta, {name: {"value", "cv", "query", "group", "runs"}})`` where
    ``value`` is the median across runs of each run's chosen timing metric, and
    ``cv`` is the cross-run coefficient of variation (0 for a single run).
    """
    reports = [_load(p) for p in paths]
    per_name = {}
    for data in reports:
        for r in data["results"]:
            per_name.setdefault(r["name"], []).append(r)
    agg = {}
    for name, recs in per_name.items():
        vals = [r[metric_key] for r in recs]
        med = statistics.median(vals)
        cv = (statistics.pstdev(vals) / med) if (len(vals) > 1 and med) else 0.0
        agg[name] = {
            "value": med,
            "cv": cv,
            # a query-count divergence anywhere across runs is worth surfacing
            "query": max(r.get("query_max", 0) for r in recs),
            "group": recs[0]["group"],
            "runs": len(recs),
        }
    # the header meta comes from the first report of the side
    return reports[0]["meta"], agg


def _fmt_speedup(s):
    if s is None:
        return "    n/a"
    return f"{s:6.2f}x"


def _marker(s, base_cv, cand_cv):
    if s is None:
        return " "
    noisy = max(base_cv or 0, cand_cv or 0) > NOISY_CV
    if s >= THRESHOLD:
        return "~+" if noisy else " +"
    if s <= 1 / THRESHOLD:
        return "~-" if noisy else " -"
    return " ="


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument(
        "-b", "--baseline", nargs="+", required=True,
        metavar="JSON", help="one or more baseline reports (e.g. upstream runs)",
    )
    ap.add_argument(
        "-c", "--candidate", nargs="+", required=True,
        metavar="JSON", help="one or more candidate reports (e.g. fork runs)",
    )
    ap.add_argument(
        "--metric",
        choices=METRIC_KEY,
        default="median",
        help="timing metric to compare (default: median)",
    )
    ap.add_argument("--md", action="store_true", help="emit a Markdown table")
    args = ap.parse_args(argv)

    key = METRIC_KEY[args.metric]
    bm, bi = _aggregate(args.baseline, key)
    cm, ci = _aggregate(args.candidate, key)
    names = sorted(set(bi) | set(ci), key=lambda n: (bi.get(n) or ci[n])["group"] + n)

    nb = len(args.baseline)
    nc = len(args.candidate)
    print(f"# ORM benchmark comparison  (metric: {args.metric}, median across runs)\n")
    print(f"  BASELINE  : {bm['label']!r:12}  py{bm['python']}  {bm['driver']}  odoo {bm['odoo_version']}  ({nb} run{'s' * (nb != 1)})")
    print(f"  CANDIDATE : {cm['label']!r:12}  py{cm['python']}  {cm['driver']}  odoo {cm['odoo_version']}  ({nc} run{'s' * (nc != 1)})")
    print(f"  host      : base={bm.get('host')!r}  cand={cm.get('host')!r}")
    print("  speedup = baseline / candidate   ( > 1.00 ⇒ candidate faster )")
    print("  '~' marks a benchmark that is noisy across runs — read its speedup as indicative only.\n")

    sep = "  " + "-" * 98
    if args.md:
        print("| benchmark | group | base µs | cand µs | speedup | queries (b→c) |")
        print("|---|---|--:|--:|--:|:--|")
    else:
        print(f"  {'benchmark':34} {'group':11} {'base µs':>11} {'cand µs':>11} {'speedup':>9}  {'queries':>11}")
        print(sep)

    speedups = []          # stable benchmarks only — used for the headline geomean
    speedups_all = []
    query_divergences = []
    only_base, only_cand = [], []

    for name in names:
        b, c = bi.get(name), ci.get(name)
        if b is None:
            only_cand.append(name)
            continue
        if c is None:
            only_base.append(name)
            continue
        bv, cvv = b["value"], c["value"]
        s = (bv / cvv) if cvv else None
        noisy = max(b["cv"], c["cv"]) > NOISY_CV
        if s:
            speedups_all.append(s)
            if not noisy:
                speedups.append(s)
        bq, cq = b["query"], c["query"]
        qstr = f"{bq}→{cq}"
        if bq != cq:
            qstr += " !!"
            query_divergences.append((name, bq, cq))
        mark = _marker(s, b["cv"], c["cv"])

        if args.md:
            print(f"| {name} | {b['group']} | {bv:.1f} | {cvv:.1f} | {_fmt_speedup(s).strip()} {mark.strip()} | {qstr} |")
        else:
            print(f"  {name:34} {b['group']:11} {bv:11.1f} {cvv:11.1f} {_fmt_speedup(s)}{mark} {qstr:>11}")

    if not args.md:
        print(sep)

    def _geo(xs):
        return math.exp(sum(math.log(x) for x in xs) / len(xs)) if xs else float("nan")

    print("\n## Summary")
    if speedups_all:
        faster = sum(1 for s in speedups_all if s >= THRESHOLD)
        slower = sum(1 for s in speedups_all if s <= 1 / THRESHOLD)
        same = len(speedups_all) - faster - slower
        print(f"  benchmarks compared : {len(speedups_all)}")
        print(f"  geomean (stable only): {_geo(speedups):.3f}x   over {len(speedups)} low-noise benchmarks")
        print(f"  geomean (all)        : {_geo(speedups_all):.3f}x   (includes noisy DB-bound ops)")
        print(f"  candidate faster    : {faster}    slower: {slower}    ~equal: {same}")
        ranked = sorted(
            ((bi[n]["value"] / ci[n]["value"], n) for n in names
             if n in bi and n in ci and ci[n]["value"]),
            reverse=True,
        )
        print("  top wins            : " + ", ".join(f"{n} ({s:.2f}x)" for s, n in ranked[:3]))
        print("  top regressions     : " + ", ".join(f"{n} ({s:.2f}x)" for s, n in ranked[-3:]))

    if query_divergences:
        print(f"\n  ⚠ query-count divergences ({len(query_divergences)}) — NOT apples-to-apples:")
        for name, bq, cq in query_divergences:
            print(f"      {name:34} baseline={bq}  candidate={cq}")
    else:
        print("\n  ✓ query counts identical on every shared benchmark")

    if only_base:
        print(f"\n  only in baseline  : {', '.join(only_base)}")
    if only_cand:
        print(f"  only in candidate : {', '.join(only_cand)}")


if __name__ == "__main__":
    main()
