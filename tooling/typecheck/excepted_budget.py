"""Per-file error budgets for the files the typecheck locks except.

``scope_gate.py`` answers one question per file: is it clean, or is it on the
exception list? For an excepted file the answer stops there. It may hold 5
errors or 500, and may go from 5 to 500 without any gate saying so — the lock
reports it as excepted either way, and the project-wide ``tsc`` ratchet absorbs
the difference as +N in a four-figure aggregate.

Measured on the day this was written: **446 excepted files carrying 6,067
errors** under ``strict``, and **577 carrying 11,383** under ``noimplicitany``.
That is 17,450 errors across 1,023 entries that nothing bounds.

Two defects had already landed through that gap:

* ``useDebounced``'s ``@returns`` narrowed ``cancel``'s arity, so the one call
  site that wanted the flush raised TS2554 while being runtime-correct.
* Tightening ``popoverService.add`` left five test mocks returning
  ``() => {}`` where the contract had become ``Promise<void>``.

Every affected file was on both exception lists. Both were found by reading.

This gate pins a **count** to each excepted entry. Membership still comes from
``exceptions/<gate>/<module>.txt`` — that file stays the single source of truth
for *which* files are excepted, and its format is untouched — while the budget
file alongside records *how many* errors each is allowed. A file that gains one
fails; a file that loses one also fails, until the lower number is committed,
which is the same drift-zero contract every other gate here uses. An entry in
one file and not the other fails too, so the two cannot silently diverge.

Usage::

    npx tsc -p tsconfig.strict.json --noEmit --listFiles > /tmp/strict.log 2>&1 || true
    python tooling/typecheck/excepted_budget.py strict --log /tmp/strict.log
    python tooling/typecheck/excepted_budget.py strict --log /tmp/strict.log --update
"""

import argparse
import json
import sys
from dataclasses import dataclass, field
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import scope_gate as sg

BUDGETS_DIR = Path(__file__).resolve().parent / "budgets"


def budget_path(gate: str, module: str) -> Path:
    for name in (gate, module):
        if not name or "/" in name or "\\" in name or name.startswith("."):
            raise ValueError(f"invalid name: {name!r}")
    return BUDGETS_DIR / f"{gate}-{module}.json"


def read_budget(gate: str, module: str) -> dict[str, int]:
    path = budget_path(gate, module)
    if not path.exists():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))["budgets"]


def write_budget(gate: str, module: str, budgets: dict[str, int], note: str) -> Path:
    path = budget_path(gate, module)
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "gate": gate,
        "module": module,
        "total": sum(budgets.values()),
        "note": note,
        "budgets": dict(sorted(budgets.items())),
    }
    path.write_text(
        json.dumps(payload, indent=2, sort_keys=False) + "\n", encoding="utf-8"
    )
    return path


def measure(gate: str, module: str, log_text: str) -> dict[str, int]:
    """Current error count for each file on the exception list."""
    tally = sg.parse_log(log_text)
    return {p: sum(tally.get(p, {}).values()) for p in sg.read_exceptions(gate, module)}


@dataclass
class Verdict:
    regressed: list[tuple[str, int, int]] = field(default_factory=list)
    improved: list[tuple[str, int, int]] = field(default_factory=list)
    unbudgeted: list[str] = field(default_factory=list)
    stale: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not (self.regressed or self.improved or self.unbudgeted or self.stale)


def evaluate(current: dict[str, int], budget: dict[str, int]) -> Verdict:
    v = Verdict()
    for path, count in sorted(current.items()):
        if path not in budget:
            v.unbudgeted.append(path)
        elif count > budget[path]:
            v.regressed.append((path, budget[path], count))
        elif count < budget[path]:
            v.improved.append((path, budget[path], count))
    v.stale = sorted(set(budget) - set(current))
    return v


def render(gate: str, module: str, current: dict[str, int], v: Verdict) -> str:
    out = [
        f"Excepted-file budget: {gate} / {module}",
        "=" * 68,
        f"{len(current)} excepted file(s), {sum(current.values())} error(s) currently",
        "",
    ]
    if v.regressed:
        out.append(f"[FAIL] {len(v.regressed)} file(s) exceeded their budget:")
        for p, was, now in v.regressed:
            out.append(f"    {p}  {was} -> {now}  (+{now - was})")
    if v.improved:
        out.append(
            f"[FAIL] {len(v.improved)} file(s) improved — lock it in with --update:"
        )
        for p, was, now in v.improved[:20]:
            out.append(f"    {p}  {was} -> {now}")
        if len(v.improved) > 20:
            out.append(f"    ... and {len(v.improved) - 20} more")
    if v.unbudgeted:
        out.append(f"[FAIL] {len(v.unbudgeted)} excepted file(s) have no budget:")
        out.extend(f"    {p}" for p in v.unbudgeted[:20])
        if len(v.unbudgeted) > 20:
            out.append(f"    ... and {len(v.unbudgeted) - 20} more")
    if v.stale:
        out.append(f"[FAIL] {len(v.stale)} budget entr(y/ies) no longer excepted:")
        out.extend(f"    {p}" for p in v.stale[:20])
    if v.ok:
        out.append("[OK] every excepted file is within its budget. No drift.")
    return "\n".join(out)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("gate", help="strict | noimplicitany")
    parser.add_argument("--module", default="web")
    parser.add_argument("--log", required=True, type=Path, help="tsc output to read")
    parser.add_argument("--update", action="store_true", help="rewrite the budget file")
    parser.add_argument("--note", default="", help="note to store with --update")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)

    if not args.log.is_file():
        print(f"error: no such log: {args.log}", file=sys.stderr)
        return 2
    log_text = args.log.read_text(encoding="utf-8", errors="replace")

    current = measure(args.gate, args.module, log_text)
    if not current:
        # An empty exception list is possible in principle; an empty *log* is
        # the likely cause and would make every budget look satisfied.
        print(
            f"error: no excepted files found for {args.gate}/{args.module} — "
            "empty exception list, or a log that parsed to nothing",
            file=sys.stderr,
        )
        return 2

    if args.update:
        path = write_budget(args.gate, args.module, current, args.note)
        print(f"wrote {path}: {len(current)} file(s), {sum(current.values())} error(s)")
        return 0

    verdict = evaluate(current, read_budget(args.gate, args.module))
    if args.json:
        print(json.dumps(verdict.__dict__, indent=2, default=list))
    else:
        print(render(args.gate, args.module, current, verdict))
    return 0 if verdict.ok else 1


if __name__ == "__main__":
    sys.exit(main())
