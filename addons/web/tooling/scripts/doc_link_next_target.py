#!/usr/bin/env python3
"""doc_link_next_target.py — rank baselined files by cleanup leverage.

Companion to ``doc_link_gate.py``; mirrors the ergonomics of the
sibling ``typecheck_next_target.mjs``: rather than asking "what should
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

  # Skip the knowledge tree (working notes accumulate rot harmlessly):
  python doc_link_next_target.py --skip-knowledge

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
import re
import sys
from dataclasses import dataclass
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[6]
DEFAULT_BASELINE_PATH = (
    REPO_ROOT
    / "addons/odoo/addons/web/tooling/scripts/doc_link_baseline.json"
)

# Authoritative surfaces — broken refs here are most damaging because
# readers trust these documents.  Mirrors the team's existing tier
# system (machine_doc_v1 is the single most read-heavy doc surface).
AUTHORITATIVE_PATHS = (
    "addons/odoo/addons/web/machine_doc_v1/",
    "addons/odoo/.github/workflows/",
    "CLAUDE.md",
    "addons/odoo/CLAUDE.md",
    "addons/odoo/addons/web/CLAUDE.md",
)

KNOWLEDGE_PATHS = (
    "knowledge/",
)


@dataclass(frozen=True)
class FileScore:
    """Aggregated score for one source file."""

    source_file: str
    total_refs: int
    avg_ease: float
    score: float
    sample_paths: tuple[str, ...]  # up to 3 example raw_paths

    @property
    def is_authoritative(self) -> bool:
        return any(self.source_file.startswith(p) for p in AUTHORITATIVE_PATHS)

    @property
    def is_knowledge(self) -> bool:
        return any(self.source_file.startswith(p) for p in KNOWLEDGE_PATHS)


def _ease_for_ref(source_file: str, raw_path: str) -> float:
    """Estimate the ease of fixing one (source, target) reference.

    Heuristic: shorter relative paths and shared directory roots
    correlate with easier fixes.  This is intentionally conservative
    — the real value comes from the file-level aggregation (some
    files have many easy refs, others have a few hard ones).
    """
    src = Path(source_file)
    tgt = raw_path.split("#", 1)[0]  # strip anchor

    # Cross-repo / aspirational refs (config/, ~/, $VAR) — already
    # filtered as placeholders by the gate, but the bare ``config/``
    # form slips through.  Hard to fix from this checkout.
    if tgt.startswith(("config/", "/home/", "/Users/")):
        return 0.3

    # Refs that look like nested plan→research patterns where the
    # cited doc usually doesn't exist (e.g. ``thoughts/tasks/t....md``
    # in plans/ files, where ``thoughts/`` isn't a real subdirectory).
    if "/thoughts/" in tgt or "/decisions/" in tgt:
        return 0.2

    # Same-directory reference (no slash in the ref) — local rename
    # or typo, easy to fix.
    if "/" not in tgt:
        return 1.0

    # Sibling-tree: target's first segment exists as a sibling of
    # source's directory.  Heuristic via shared prefix length.
    src_parts = src.parts
    tgt_first = tgt.split("/", 1)[0]
    if tgt_first in src_parts[:-1]:
        # Probably a parent-relative ref written without ``../``
        return 0.9

    # In-repo cross-tree.
    if tgt.startswith(("addons/", "knowledge/", "core/")):
        return 0.7

    return 0.5  # unknown


def score_files(baseline: dict, *, include_knowledge: bool = True) -> list[FileScore]:
    """Aggregate baseline violations into per-file scores."""
    by_file: dict[str, list[tuple[str, float]]] = {}
    for v in baseline.get("violations", []):
        sf = v["source_file"]
        rp = v["raw_path"]
        ease = _ease_for_ref(sf, rp)
        by_file.setdefault(sf, []).append((rp, ease))

    scores: list[FileScore] = []
    for sf, refs in by_file.items():
        if not include_knowledge and any(
            sf.startswith(p) for p in KNOWLEDGE_PATHS
        ):
            continue
        total = len(refs)
        avg_ease = sum(e for _, e in refs) / total
        score = total * avg_ease
        # Sample up to 3 distinct raw paths for orientation.
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


def _print_table(rows: list[FileScore], limit: int) -> None:
    """Pretty-print the ranked list."""
    if not rows:
        print("(no candidates — baseline is empty?)")
        return
    name_w = max(len(r.source_file) for r in rows[:limit])
    name_w = min(name_w, 80)  # cap width for narrow terminals
    print(f"{'#':>2}  {'score':>6}  {'refs':>4}  {'ease':>4}  source_file")
    print(f"{'─'*2}  {'─'*6}  {'─'*4}  {'─'*4}  {'─' * name_w}")
    for i, r in enumerate(rows[:limit], 1):
        sf = r.source_file
        if len(sf) > name_w:
            sf = "…" + sf[-(name_w - 1):]
        print(
            f"{i:>2}  {r.score:>6.1f}  {r.total_refs:>4}  "
            f"{r.avg_ease:>4.2f}  {sf}"
        )
        for rp in r.sample_paths[:2]:
            print(f"      · `{rp}`")


def _main() -> int:
    parser = argparse.ArgumentParser(
        description="Rank doc-link baseline files by cleanup leverage."
    )
    parser.add_argument("--baseline", type=Path, default=DEFAULT_BASELINE_PATH)
    parser.add_argument("--limit", type=int, default=10)
    parser.add_argument(
        "--authoritative-only",
        action="store_true",
        help="Only show files in machine_doc/, CI workflows, and CLAUDE.md.",
    )
    parser.add_argument(
        "--skip-knowledge",
        action="store_true",
        help="Skip the knowledge/ tree (working notes accumulate rot).",
    )
    args = parser.parse_args()

    if not args.baseline.exists():
        print(
            f"✗ Baseline not found at {args.baseline}.\n"
            f"  Run ``doc_link_gate.py --update-baseline`` first.",
            file=sys.stderr,
        )
        return 2

    baseline = json.loads(args.baseline.read_text())
    scores = score_files(baseline, include_knowledge=not args.skip_knowledge)
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
    _print_table(scores, args.limit)
    return 0


if __name__ == "__main__":
    raise SystemExit(_main())
