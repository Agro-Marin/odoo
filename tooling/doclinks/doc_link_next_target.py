#!/usr/bin/env python3


from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass
from pathlib import Path

DEFAULT_BASELINE_PATH = (
    Path(__file__).resolve().parent / "baselines" / "doc_link_baseline.json"
)

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
    if not rows:
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
