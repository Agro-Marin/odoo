#!/usr/bin/env python3
"""doc_link_next_target.py — rank baselined files by cleanup leverage.

Companion to ``doc_link_gate.py``; mirrors the ergonomics of the
sibling ``tooling/typecheck/scope_gate.py --report``: rather than asking "what should
I fix?" each cleanup-hour cadence, this script reads the current
baseline and prints the top-N candidates ordered by (violation count
× per-violation ease).

The team picks one, fixes it, runs ``doc_link_gate.py --update-baseline``
to refresh, and the next picker run reflects the new state.

USAGE
-----

  # Top 10 files (default):
  python doc_link_next_target.py

  # Top 25:
  python doc_link_next_target.py --limit=25

  # Only authoritative surfaces (machine_doc, CI, top-level CLAUDE.md):
  # — these are highest-priority because broken refs there mislead
  # readers about how the system works.
  python doc_link_next_target.py --authoritative-only

  # Alternate baseline:
  python doc_link_next_target.py --baseline=PATH

EASE SCORE
----------

Per-violation difficulty heuristic, calibrated by manual inspection of a
baseline snapshot (~500 violations) in May 2026:

  1.0 — same-directory reference (typo or local rename)
  0.9 — sibling-tree reference (e.g. ``doc/X.md`` from
        ``machine_doc_v1/``; just need to fix the relative path)
  0.7 — cross-tree but in-repo (the doc was renamed or relocated;
        find the new home and update the citing file)
  0.5 — DEFAULT — unknown ease
  0.3 — cross-repo / aspirational (refs to ``config/...`` files
        that live in the agent-config repo, not the Odoo checkout;
        either delete the citing line or document the cross-repo
        convention explicitly)
  0.2 — deep nested plan→research refs (often the cited doc was
        never written; needs author archaeology)

Score per file = total_violations × avg_ease.  Higher = better
candidate (lots of broken refs that are likely easy to fix together).
"""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass
from pathlib import Path

DEFAULT_BASELINE_PATH = (
    Path(__file__).resolve().parent / "baselines" / "doc_link_baseline.json"
)

# Surfaces where a broken reference actively misleads a reader about how the
# system works, as opposed to merely rotting. Kept in step with
# ``doc_link_gate.DEFAULT_SCAN_GLOBS``: every machine_doc tree (not just web's),
# the workflows and the CLAUDE.md surfaces.
AUTHORITATIVE_PATHS = (
    "addons/web/machine_doc_v1/",
    ".github/workflows/",
    "CLAUDE.md",
    "addons/web/CLAUDE.md",
    "tooling/",
)


def _is_machine_doc(source_file: str) -> bool:
    return "/machine_doc_v1/" in source_file


@dataclass(frozen=True)
class FileScore:
    """Aggregated score for one source file."""

    source_file: str
    total_refs: int
    avg_ease: float
    score: float
    sample_paths: tuple[str, ...]

    @property
    def is_authoritative(self) -> bool:
        return _is_machine_doc(self.source_file) or any(
            self.source_file.startswith(p) for p in AUTHORITATIVE_PATHS
        )


def _ease_for_ref(source_file: str, raw_path: str) -> float:
    """Estimate the ease of fixing one (source, target) reference.

    Heuristic: shorter relative paths and shared directory roots
    correlate with easier fixes.  This is intentionally conservative
    — the real value comes from the file-level aggregation (some
    files have many easy refs, others have a few hard ones).
    """
    src = Path(source_file)
    tgt = raw_path.split("#", 1)[0]

    if tgt.startswith(("config/", "/home/", "/Users/")):
        return 0.3

    if "/thoughts/" in tgt or "/decisions/" in tgt:
        return 0.2

    if "/" not in tgt:
        return 1.0

    src_parts = src.parts
    tgt_first = tgt.split("/", 1)[0]
    if tgt_first in src_parts[:-1]:
        return 0.9

    if tgt.startswith(("addons/", "odoo/", "doc/")):
        return 0.7

    return 0.5


def score_files(baseline: dict) -> list[FileScore]:
    """Aggregate baseline violations into per-file scores."""
    by_file: dict[str, list[tuple[str, float]]] = {}
    for v in baseline.get("violations", []):
        sf = v["source_file"]
        rp = v["raw_path"]
        ease = _ease_for_ref(sf, rp)
        by_file.setdefault(sf, []).append((rp, ease))

    scores: list[FileScore] = []
    for sf, refs in by_file.items():
        total = len(refs)
        avg_ease = sum(e for _, e in refs) / total
        score = total * avg_ease
        seen: set[str] = set()
        samples: list[str] = []
        for rp, _ in refs:
            if rp not in seen:
                seen.add(rp)
                samples.append(rp)
                if len(samples) == 3:
                    break
        scores.append(
            FileScore(
                source_file=sf,
                total_refs=total,
                avg_ease=avg_ease,
                score=score,
                sample_paths=tuple(samples),
            )
        )
    return scores


def _print_table(
    rows: list[FileScore], limit: int, *, from_baseline: bool = False
) -> None:
    """Pretty-print the ranked list."""
    if not rows:
        # The default source is the LIVE tree, not the baseline — so an empty
        # result normally means the gate is clean, which is the good outcome
        # and should not be reported as a suspected empty baseline.
        print(
            "(nothing to rank — the committed baseline is empty)"
            if from_baseline
            else "(nothing to rank — every .md reference in scope resolves)"
        )
        return
    name_w = max(len(r.source_file) for r in rows[:limit])
    name_w = min(name_w, 80)
    print(f"{'#':>2}  {'score':>6}  {'refs':>4}  {'ease':>4}  source_file")
    print(f"{'─' * 2}  {'─' * 6}  {'─' * 4}  {'─' * 4}  {'─' * name_w}")
    for i, r in enumerate(rows[:limit], 1):
        sf = r.source_file
        if len(sf) > name_w:
            sf = "…" + sf[-(name_w - 1) :]
        print(f"{i:>2}  {r.score:>6.1f}  {r.total_refs:>4}  {r.avg_ease:>4.2f}  {sf}")
        for rp in r.sample_paths[:2]:
            print(f"      · `{rp}`")


def _live_violations() -> dict:
    """Scan the tree now, in the baseline's shape.

    Ranking the committed baseline answers "what was broken when someone last
    ran --update-baseline", which is not the question. Measured on this tree it
    had drifted both ways: 72 of its 478 entries were already fixed, and 81
    live violations were absent from it — so the ranker sent you at work that
    was done and hid work that was not. The sibling ``scope_gate --report``
    reads the live tsc log for exactly this reason. A scan costs ~0.5s.
    """
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    from doc_link_gate import scan

    return {
        "violations": [
            {"source_file": v.source_file, "raw_path": v.raw_path} for v in scan()
        ]
    }


def _main() -> int:
    parser = argparse.ArgumentParser(
        description="Rank doc-link baseline files by cleanup leverage."
    )
    parser.add_argument("--baseline", type=Path, default=DEFAULT_BASELINE_PATH)
    parser.add_argument("--limit", type=int, default=10)
    parser.add_argument(
        "--from-baseline",
        action="store_true",
        help=(
            "Rank the committed baseline instead of the live tree. Faster, but "
            "only as accurate as the last --update-baseline."
        ),
    )
    parser.add_argument(
        "--authoritative-only",
        action="store_true",
        help="Only show files in machine_doc/, CI workflows, and CLAUDE.md.",
    )
    args = parser.parse_args()

    if args.from_baseline:
        if not args.baseline.exists():
            print(
                f"✗ Baseline not found at {args.baseline}.\n"
                f"  Run ``doc_link_gate.py --update-baseline`` first.",
                file=sys.stderr,
            )
            return 2
        baseline = json.loads(args.baseline.read_text(encoding="utf-8"))
    else:
        baseline = _live_violations()
    scores = score_files(baseline)
    if args.authoritative_only:
        scores = [s for s in scores if s.is_authoritative]
    scores.sort(key=lambda s: s.score, reverse=True)

    total_files = len(scores)
    total_refs = sum(s.total_refs for s in scores)
    print(
        f"Doc-link cleanup candidates "
        f"(top {min(args.limit, total_files)} of {total_files}, "
        f"{total_refs} refs total):\n"
    )
    _print_table(scores, args.limit, from_baseline=args.from_baseline)
    return 0


if __name__ == "__main__":
    raise SystemExit(_main())
