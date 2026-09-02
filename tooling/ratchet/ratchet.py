#!/usr/bin/env python3


from __future__ import annotations

import argparse
import json
import subprocess
import sys
from dataclasses import asdict, dataclass, replace
from pathlib import Path

HERE = Path(__file__).resolve().parent
BASELINES_DIR = HERE / "baselines"
ODOO_ROOT = HERE.parents[1]
WORKSPACE = ODOO_ROOT.parent
# A gate named <name>_<sibling> measures that sibling checkout, so the tree
# that has to be clean when it is banked, and the history its stamp lives in,
# are the sibling's -- not this repository's.
SIBLING_ROOTS = ("enterprise", "agromarin", "design-themes")

EXIT_OK = 0
EXIT_DRIFT = 1
EXIT_USAGE = 2


def gate_sibling(gate: str) -> str:
    """The sibling a gate's name says it measures, or "" for this repository."""
    return next((s for s in SIBLING_ROOTS if gate.endswith(f"_{s}")), "")


def repo_dir(root: str) -> Path:
    return WORKSPACE / root if root else ODOO_ROOT


def _head_commit(root: str = "") -> str:
    """The commit a measurement is being banked against, or "" if unknowable."""
    try:
        out = subprocess.run(
            ["git", "-C", str(repo_dir(root)), "rev-parse", "HEAD"],
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
        )
    except OSError, subprocess.SubprocessError:
        return ""
    return out.stdout.strip() if out.returncode == 0 else ""


def _dirty_paths(root: str = "") -> list[str] | None:
    """Paths the working tree changes against HEAD, or None if git cannot say."""
    try:
        out = subprocess.run(
            [
                "git",
                "-C",
                str(repo_dir(root)),
                "status",
                "--porcelain",
                "--untracked-files=all",
            ],
            capture_output=True,
            text=True,
            timeout=30,
            check=False,
        )
    except OSError, subprocess.SubprocessError:
        return None
    if out.returncode != 0:
        return None
    return [line[3:] for line in out.stdout.splitlines() if line.strip()]


def _is_ancestor_of_head(commit: str, root: str = "") -> bool | None:
    """True/False, or None when git cannot answer (no git, unknown object)."""
    if not commit:
        return None
    try:
        out = subprocess.run(
            [
                "git",
                "-C",
                str(repo_dir(root)),
                "merge-base",
                "--is-ancestor",
                commit,
                "HEAD",
            ],
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
        )
    except OSError, subprocess.SubprocessError:
        return None
    if out.returncode == 0:
        return True
    if out.returncode == 1:
        return False
    return None  # 128: not a repository, or the object is gone


@dataclass(frozen=True)
class Baseline:
    count: int
    note: str = ""
    # The commit HEAD pointed at when this count was banked.  Recorded because
    # five floors were once banked against a detached pre-rebase worktree and
    # were wrong the moment they landed -- and establishing that took measuring
    # the gate in an archive tree at eight commits.  With this, the same
    # question is `git merge-base --is-ancestor`: a floor whose measured_at is
    # not in HEAD's history was taken from a tree this branch never had.
    measured_at: str = ""
    # Which checkout measured_at belongs to: "" for this repository, else a
    # sibling's directory name.  A sibling-scoped floor banked before this
    # field existed carries an odoo commit here, which resolves cleanly in
    # the wrong repository; --list renders that as STAMP-PREDATES-ROOT.
    measured_root: str = ""

    @classmethod
    def load(cls, gate: str) -> Baseline | None:
        path = baseline_path(gate)
        if not path.exists():
            return None
        data = json.loads(path.read_text(encoding="utf-8"))
        return cls(
            count=int(data["count"]),
            note=str(data.get("note", "")),
            measured_at=str(data.get("measured_at", "")),
            measured_root=str(data.get("measured_root", "")),
        )

    def save(self, gate: str) -> Path:
        path = baseline_path(gate)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps(asdict(self), indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        return path


# A gate with no baseline file is held at zero.  The file records debt -- a
# count above zero and what moved it -- so a count born at zero has nothing to
# record, and `--list` stays a list of debt rather than of every contract.
HARD_ZERO = Baseline(count=0)


def hard_zero_hint(gate: str, count: int) -> str:
    return (
        f"{gate} has no {baseline_path(gate).name}, so its floor is zero: a "
        f"contract, not debt. Fix the finding. Opening a floor instead "
        f"(ratchet.py {gate} --count {count} --update --note '...') turns the "
        f"contract into debt, and the note has to argue why."
    )


def baseline_path(gate: str) -> Path:
    if not gate or "/" in gate or "\\" in gate or gate.startswith("."):
        raise ValueError(f"invalid gate name: {gate!r}")
    return BASELINES_DIR / f"{gate}.json"


@dataclass(frozen=True)
class Verdict:
    gate: str
    count: int
    baseline: int
    mode: str
    ok: bool
    status: str
    message: str

    @property
    def drift(self) -> int:
        return self.count - self.baseline


def evaluate(gate: str, count: int, baseline: Baseline, mode: str) -> Verdict:
    drift = count - baseline.count
    if drift > 0:
        return Verdict(
            gate,
            count,
            baseline.count,
            mode,
            ok=False,
            status="regressed",
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
                gate,
                count,
                baseline.count,
                mode,
                ok=False,
                status="improved",
                message=(
                    f"{improved} — lock it in: rerun with --update so the floor "
                    f"drops to {count} and can never slip back."
                ),
            )
        return Verdict(
            gate,
            count,
            baseline.count,
            mode,
            ok=True,
            status="improved",
            message=f"{improved}; consider --update to lock the lower floor.",
        )
    return Verdict(
        gate,
        count,
        baseline.count,
        mode,
        ok=True,
        status="unchanged",
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
    parser.add_argument(
        "--root",
        choices=("odoo", *SIBLING_ROOTS),
        default=None,
        help="with --update, the checkout the count was measured over; required "
        "for a gate named <name>_<sibling>, whose clean tree and history are the "
        "sibling's",
    )
    parser.add_argument("--json", action="store_true", help="machine-readable output")
    parser.add_argument(
        "--list", action="store_true", help="list all baselines and exit"
    )
    parser.add_argument(
        "--notes",
        action="store_true",
        help="with --list, print each floor's note under it",
    )
    args = parser.parse_args(argv)

    if args.list:
        return _list_baselines(as_json=args.json, notes=args.notes)

    if not args.gate or args.count is None:
        parser.error("a gate name and --count are required (or use --list)")

    try:
        existing = Baseline.load(args.gate)
    except (OSError, ValueError, KeyError, TypeError, json.JSONDecodeError) as exc:
        print(f"error: bad baseline for {args.gate!r}: {exc}", file=sys.stderr)
        return EXIT_USAGE

    if args.update:
        sibling = gate_sibling(args.gate)
        if sibling and args.root is None:
            print(
                f"error: {args.gate!r} measures the {sibling!r} checkout; pass "
                f"--root {sibling} so the tree that has to be clean, and the "
                f"commit the stamp names, are that repository's.",
                file=sys.stderr,
            )
            return EXIT_USAGE
        root = "" if args.root in (None, "odoo") else args.root
        dirty = _dirty_paths(root)
        if dirty:
            # A floor is a claim about a commit.  Banking one from a tree that
            # differs from HEAD records a count nobody can reproduce from the
            # commit the stamp names -- and on a shared checkout it banks other
            # people's uncommitted work as this branch's debt.
            print(
                f"error: refusing to bank {args.gate!r} from a dirty "
                f"{root or 'odoo'} tree ({len(dirty)} changed or untracked "
                f"path(s), e.g. {dirty[0]!r}). Measure on a clean worktree of the "
                f"commit you mean to stamp.",
                file=sys.stderr,
            )
            return EXIT_USAGE
        note = (
            args.note if args.note is not None else (existing.note if existing else "")
        )
        path = Baseline(
            count=args.count,
            note=note,
            measured_at=_head_commit(root),
            measured_root=root,
        ).save(args.gate)
        verb = "updated" if existing else "created"
        old = f" (was {existing.count})" if existing else ""
        print(f"{verb} baseline {path.name}: count={args.count}{old}")
        return EXIT_OK

    if (
        existing is not None
        and _is_ancestor_of_head(existing.measured_at, existing.measured_root) is False
    ):
        # The stamp names a commit this branch's history does not contain: the
        # count was measured on a tree this branch never had, so comparing the
        # live count against it answers nothing.  Re-measure and re-bank.
        print(
            f"error: {args.gate}'s floor was banked at {existing.measured_at[:12]}, "
            f"which is not in HEAD's history (ORPHANED-BASE). Re-measure on a clean "
            f"worktree of HEAD and re-bank with --update; a comparison against "
            f"that floor is not a reading.",
            file=sys.stderr,
        )
        return EXIT_USAGE

    verdict = evaluate(args.gate, args.count, existing or HARD_ZERO, args.mode)
    if existing is None and not verdict.ok:
        verdict = replace(
            verdict,
            message=f"{verdict.message}\n{hard_zero_hint(args.gate, args.count)}",
        )
    if args.json:
        print(json.dumps(asdict(verdict), indent=2, sort_keys=True))
    else:
        mark = "OK" if verdict.ok else "FAIL"
        print(f"[{mark}] {verdict.message}")
    return EXIT_OK if verdict.ok else EXIT_DRIFT


def _note_lines(note: str) -> list[str]:
    return [line.rstrip() for line in note.strip().splitlines()] or [""]


def _list_baselines(*, as_json: bool, notes: bool = False) -> int:
    rows = []
    broken = []
    if BASELINES_DIR.exists():
        for path in sorted(BASELINES_DIR.glob("*.json")):
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
                measured_at = str(data.get("measured_at", ""))
                measured_root = str(data.get("measured_root", ""))
                ancestry = _is_ancestor_of_head(measured_at, measured_root)
                rows.append(
                    {
                        "gate": path.stem,
                        "count": int(data["count"]),
                        "note": str(data.get("note", "")),
                        "measured_at": measured_at,
                        "measured_root": measured_root,
                        "orphaned": ancestry is False,
                        "unchecked": ancestry is None and bool(measured_at),
                        "predates_root": bool(measured_at)
                        and not measured_root
                        and bool(gate_sibling(path.stem)),
                    }
                )
            except (OSError, ValueError, KeyError, TypeError) as exc:
                broken.append(
                    {"gate": path.stem, "error": f"{type(exc).__name__}: {exc}"}
                )
    if as_json:
        print(
            json.dumps({"baselines": rows, "broken": broken}, indent=2, sort_keys=True)
        )
    else:
        if not rows and not broken:
            print("no baselines yet")
        width = max((len(r["gate"]) for r in rows + broken), default=0)
        for row in rows:
            if row["orphaned"]:
                flag = "  ORPHANED-BASE"
            elif row["predates_root"]:
                # The stamp is an odoo commit and the count was taken over a
                # sibling: it resolves cleanly in the wrong repository.
                flag = "  STAMP-PREDATES-ROOT"
            elif row["unchecked"]:
                # Unknowable is not wrong, so this is deliberately not
                # ORPHANED-BASE -- but it is not clean either, and rendering it
                # blank made a floor stamped on a vanished commit look verified.
                flag = "  UNCHECKED"
            else:
                flag = ""
            print(f"{row['gate']:<{width}} {row['count']:>8}{flag}")
            if notes:
                for line in _note_lines(row["note"]):
                    print(f"{'':<{width}} {'':>8}   {line}")
        for row in broken:
            print(
                f"{row['gate']:<{width}} {'BROKEN':>8}   {row['error']}",
                file=sys.stderr,
            )
        orphaned = [r["gate"] for r in rows if r["orphaned"]]
        if orphaned:
            print(
                f"\n{len(orphaned)} floor(s) banked at a commit that is not in "
                f"HEAD's history: {', '.join(orphaned)}.\n"
                f"Their count was measured on a tree this branch never had, so it "
                f"may never have been true. Re-measure before trusting one."
            )
        predates = [r["gate"] for r in rows if r["predates_root"]]
        if predates:
            print(
                f"\n{len(predates)} sibling-scoped floor(s) stamped before --root "
                f"existed: {', '.join(predates)}.\n"
                f"Their stamp is an odoo commit, so it resolves in the wrong "
                f"repository and says nothing about the tree that was measured. "
                f"The next --update --root <sibling> records the sibling's commit."
            )
        unchecked = [r["gate"] for r in rows if r["unchecked"]]
        if unchecked:
            print(
                f"\n{len(unchecked)} floor(s) whose stamped commit git could not "
                f"resolve: {', '.join(unchecked)}.\n"
                f"That is unknowable rather than wrong -- but it is not a verified "
                f"base either, so it cannot be read as clean."
            )
        if rows and not notes:
            print(f"\n{len(rows)} floor(s). --notes prints what moved each one.")
    return EXIT_USAGE if broken else EXIT_OK


if __name__ == "__main__":
    raise SystemExit(run())
