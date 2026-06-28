#!/usr/bin/env python3
"""Drift-zero ratchet for countable quality gates (mypy, lint, tsc, ...).

This is the generalisation of ``tooling/architecture/layer_check.py``'s
drift-zero idea to *any* gate that can be reduced to a single number: a count of
type errors, lint findings, ``# type: ignore`` comments, free-threading
warnings, and so on. The architecture checker proved the pattern works
(``KNOWN_VIOLATIONS`` pinned, fails on any new crossing); this tool gives every
other gate the same teeth without re-implementing the bookkeeping each time.

Why this exists
---------------
Several CI gates (``py_typecheck.yml``, ``lint.yml``, ``typecheck.yml``,
``freethreading.yml``) historically computed a ``DRIFT = COUNT - BASELINE`` and
then only ``echo``-ed it: ``continue-on-error: true`` plus no ``exit 1`` meant a
PR could add 500 new errors and still merge green. A baseline that nothing
enforces is a comment, not a gate. This tool turns the number into a contract.

The ratchet only moves one way. An *increase* is a regression and fails. A
*decrease* is an improvement — and in the default ``exact`` mode it also fails,
with a message telling you to commit the lower baseline, so the win is locked in
and can never silently slip back. That is what makes improvements compound: the
floor rises every time, mechanically.

Usage
-----
    # CI: compute the count however the gate naturally does, then compare.
    ratchet.py mypy --count 1969               # exit 1 if != committed baseline
    ratchet.py mypy --count 1969 --mode no-increase   # exit 1 only if > baseline

    # Maintainer: set or lower a baseline (the only way the floor moves).
    ratchet.py mypy --count 1900 --update      # writes baselines/mypy.json

    ratchet.py mypy --count 1969 --json        # machine-readable verdict
    ratchet.py --list                          # show all baselines

Baselines live in ``tooling/ratchet/baselines/<gate>.json`` — one small file per
gate so diffs are obvious and merge conflicts are trivial to resolve. Each PR
that changes a count must move its baseline in the same commit, which makes the
ratchet's state reviewable in the diff rather than hidden in CI logs.
"""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import asdict, dataclass
from pathlib import Path

# This file lives at ``<root>/tooling/ratchet/ratchet.py``.
HERE = Path(__file__).resolve().parent
BASELINES_DIR = HERE / "baselines"

# Exit codes (stable, for CI to branch on).
EXIT_OK = 0
EXIT_DRIFT = 1  # the gate moved away from its baseline — block.
EXIT_USAGE = 2  # misconfiguration (missing baseline, bad args) — fix the setup.


@dataclass(frozen=True)
class Baseline:
    """The committed floor for one gate.

    :param count: the locked count. CI fails unless the live count matches (or,
        in ``no-increase`` mode, does not exceed) this number.
    :param note: free text — what the count measures and how it is produced, so
        the baseline file is self-explanatory in review.
    """

    count: int
    note: str = ""

    @classmethod
    def load(cls, gate: str) -> Baseline | None:
        path = baseline_path(gate)
        if not path.exists():
            return None
        data = json.loads(path.read_text(encoding="utf-8"))
        return cls(count=int(data["count"]), note=str(data.get("note", "")))

    def save(self, gate: str) -> Path:
        path = baseline_path(gate)
        path.parent.mkdir(parents=True, exist_ok=True)
        # Trailing newline + sorted keys: stable, diff-friendly, POSIX-clean.
        path.write_text(
            json.dumps(asdict(self), indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        return path


def baseline_path(gate: str) -> Path:
    if not gate or "/" in gate or "\\" in gate or gate.startswith("."):
        raise ValueError(f"invalid gate name: {gate!r}")
    return BASELINES_DIR / f"{gate}.json"


@dataclass(frozen=True)
class Verdict:
    """The result of comparing a live count to a baseline."""

    gate: str
    count: int
    baseline: int
    mode: str
    ok: bool
    status: str  # "unchanged" | "regressed" | "improved" | "set"
    message: str

    @property
    def drift(self) -> int:
        return self.count - self.baseline


def evaluate(gate: str, count: int, baseline: Baseline, mode: str) -> Verdict:
    """Compare ``count`` against ``baseline`` under ``mode``. Pure function."""
    drift = count - baseline.count
    if drift > 0:
        return Verdict(
            gate, count, baseline.count, mode, ok=False, status="regressed",
            message=(
                f"{gate}: {count} > baseline {baseline.count} "
                f"(+{drift}). Regression — bring the count back down, or, if the "
                f"increase is genuinely unavoidable, raise the baseline in the "
                f"same commit (visible in review)."
            ),
        )
    if drift < 0:
        improved = (
            f"{gate}: {count} < baseline {baseline.count} ({drift}). "
            f"Improvement detected"
        )
        if mode == "exact":
            return Verdict(
                gate, count, baseline.count, mode, ok=False, status="improved",
                message=(
                    f"{improved} — lock it in: rerun with --update so the floor "
                    f"drops to {count} and can never slip back."
                ),
            )
        return Verdict(
            gate, count, baseline.count, mode, ok=True, status="improved",
            message=f"{improved}; consider --update to lock the lower floor.",
        )
    return Verdict(
        gate, count, baseline.count, mode, ok=True, status="unchanged",
        message=f"{gate}: {count} == baseline. No drift.",
    )


def run(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="ratchet.py",
        description="Drift-zero ratchet for countable quality gates.",
    )
    parser.add_argument("gate", nargs="?", help="gate name (e.g. mypy, lint, tsc)")
    parser.add_argument("--count", type=int, help="the live count to check")
    parser.add_argument(
        "--mode",
        choices=("exact", "no-increase"),
        default="exact",
        help="exact (default): count must equal the baseline; improvements must "
        "be committed. no-increase: only an increase fails.",
    )
    parser.add_argument(
        "--update",
        action="store_true",
        help="write the baseline to --count (the only way the floor moves).",
    )
    parser.add_argument("--note", default=None, help="note to store with --update")
    parser.add_argument("--json", action="store_true", help="machine-readable output")
    parser.add_argument("--list", action="store_true", help="list all baselines and exit")
    args = parser.parse_args(argv)

    if args.list:
        return _list_baselines(as_json=args.json)

    if not args.gate or args.count is None:
        parser.error("a gate name and --count are required (or use --list)")

    try:
        existing = Baseline.load(args.gate)
    except (ValueError, KeyError, json.JSONDecodeError) as exc:
        print(f"error: bad baseline for {args.gate!r}: {exc}", file=sys.stderr)
        return EXIT_USAGE

    if args.update:
        note = args.note if args.note is not None else (existing.note if existing else "")
        path = Baseline(count=args.count, note=note).save(args.gate)
        verb = "updated" if existing else "created"
        old = f" (was {existing.count})" if existing else ""
        print(f"{verb} baseline {path.name}: count={args.count}{old}")
        return EXIT_OK

    if existing is None:
        print(
            f"error: no baseline for {args.gate!r}. Set one with:\n"
            f"  ratchet.py {args.gate} --count {args.count} --update",
            file=sys.stderr,
        )
        return EXIT_USAGE

    verdict = evaluate(args.gate, args.count, existing, args.mode)
    if args.json:
        print(json.dumps(asdict(verdict), indent=2, sort_keys=True))
    else:
        mark = "OK" if verdict.ok else "FAIL"
        print(f"[{mark}] {verdict.message}")
    return EXIT_OK if verdict.ok else EXIT_DRIFT


def _list_baselines(*, as_json: bool) -> int:
    rows = []
    if BASELINES_DIR.exists():
        for path in sorted(BASELINES_DIR.glob("*.json")):
            data = json.loads(path.read_text(encoding="utf-8"))
            rows.append({"gate": path.stem, "count": data["count"], "note": data.get("note", "")})
    if as_json:
        print(json.dumps(rows, indent=2, sort_keys=True))
    else:
        if not rows:
            print("no baselines yet")
        for row in rows:
            print(f"{row['gate']:<16} {row['count']:>8}   {row['note']}")
    return EXIT_OK


if __name__ == "__main__":
    raise SystemExit(run())
