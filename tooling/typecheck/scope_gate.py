#!/usr/bin/env python3


from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import asdict, dataclass, field
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from _repo_root import find_odoo_root

HERE = Path(__file__).resolve().parent
ROOT = find_odoo_root(Path(__file__).resolve(), tool="scope_gate")
EXCEPTIONS_DIR = HERE / "exceptions"

SCOPED_MODULES = ("web",)

SCOPE_SUBDIRS = ("src", "tests")

CHECKED_SUFFIXES = (".js", ".ts")

PROGRAM_SUFFIXES = (".js", ".ts", ".jsx", ".tsx", ".json")

MODULE_PATH_RE = re.compile(
    r"^addons/(?P<module>[^/]+)/static/(?P<subdir>%s)/" % "|".join(SCOPE_SUBDIRS)
)

ERROR_LINE_RE = re.compile(
    r"^(?P<path>[^(\s][^(]*?)\((?P<line>\d+),(?P<col>\d+)\): error (?P<code>TS\d+): "
)

EXIT_OK = 0
EXIT_DRIFT = 1
EXIT_USAGE = 2

CODE_EASE = {
    "TS18047": 1.0,
    "TS18048": 1.0,
    "TS2532": 1.0,
    "TS2531": 1.0,
    "TS2454": 0.9,
    "TS7006": 0.8,
    "TS7005": 0.8,
    "TS7031": 0.8,
    "TS7034": 0.7,
    "TS2554": 0.5,
    "TS2322": 0.4,
    "TS2345": 0.3,
    "TS2339": 0.3,
    "TS2353": 0.3,
}
DEFAULT_EASE = 0.5


def excluded_from_program() -> frozenset[str]:
    """The literal paths ``tsconfig.json`` keeps out of the DOM program.

    A file the main program never compiles is not this gate's to lock. It has
    either moved to another lane — the service workers are checked by
    ``tsconfig.serviceworker.*.json`` against ``lib.webworker``, because DOM and
    WebWorker cannot share a program — or to nothing at all. Either way an
    exception entry for it asserts nothing, and without this it would keep
    asserting nothing forever: an excluded path that is already excepted is
    subtracted from ``unchecked`` (see ``evaluate``), so it goes on counting
    toward coverage while no compiler looks at it. That is the ``l10n*`` hole in
    the other direction, and it is how ``web/static/src/service_worker.js``
    behaved the moment it left the program.

    Read from the tsconfig rather than restated here, for the reason
    ``is_hidden`` matches tsc's own dotfile rule instead of carrying a list:
    a second source of truth for what the program contains drifts from the
    first. Only literal entries are honoured — the globs (``addons/l10n_*``,
    ``**/lib/…``) name directories this gate's scope never reaches.
    """
    tsconfig = ROOT / "tsconfig.json"
    if not tsconfig.is_file():
        # No tsconfig, nothing excluded. Reached only by the self-tests, which
        # point ROOT at a temp tree; a real checkout always has one, and a
        # missing one is the caller's problem to notice, not this gate's to
        # guess at.
        return frozenset()
    text = re.sub(r"//.*", "", tsconfig.read_text(encoding="utf8"))
    return frozenset(
        entry
        for entry in json.loads(text).get("exclude", [])
        if not any(ch in entry for ch in "*?")
    )


def module_of(path: str) -> str | None:
    if not path.endswith(CHECKED_SUFFIXES) or path.endswith(".d.ts"):
        return None
    if path in excluded_from_program():
        return None
    match = MODULE_PATH_RE.match(path)
    if not match or match["module"] not in SCOPED_MODULES:
        return None
    return match["module"]


def in_scope(path: str) -> bool:
    return module_of(path) is not None


def parse_log(text: str) -> dict[str, dict[str, int]]:

    tally: dict[str, dict[str, int]] = {}
    for raw in text.splitlines():
        match = ERROR_LINE_RE.match(raw)
        if not match:
            continue
        path = _normalise(match["path"])
        tally.setdefault(path, {}).setdefault(match["code"], 0)
        tally[path][match["code"]] += 1
    return tally


def _normalise(path: str) -> str:
    path = path.strip().replace("\\", "/")
    path = path.removeprefix(ROOT.as_posix() + "/")
    while path.startswith("./"):
        path = path.removeprefix("./")
    return path


def parse_program_files(text: str) -> set[str]:

    files = set()
    for raw in text.splitlines():
        line = raw.strip()
        if not line or ERROR_LINE_RE.match(raw):
            continue
        if not line.endswith(PROGRAM_SUFFIXES):
            continue
        normalised = _normalise(line)
        if " " in line and not (ROOT / normalised).exists():
            continue
        files.add(normalised)
    return files


def exceptions_path(gate: str, module: str) -> Path:
    for name in (gate, module):
        if not name or "/" in name or "\\" in name or name.startswith("."):
            raise ValueError(f"invalid name: {name!r}")
    return EXCEPTIONS_DIR / gate / f"{module}.txt"


def read_exceptions(gate: str, module: str) -> list[str]:
    path = exceptions_path(gate, module)
    if not path.exists():
        return []
    entries = []
    for raw in path.read_text(encoding="utf-8").splitlines():
        entry = raw.strip()
        if entry and not entry.startswith("#"):
            entries.append(entry)
    return entries


def write_exceptions(gate: str, module: str, paths: list[str]) -> Path:
    path = exceptions_path(gate, module)
    path.parent.mkdir(parents=True, exist_ok=True)
    header = UPDATE_HEADER.format(
        gate=gate,
        module=module,
        scope=", ".join(module_prefixes(module)),
    )
    body = "".join(f"{p}\n" for p in sorted(set(paths)))
    path.write_text(header + body, encoding="utf-8")
    return path


def module_prefixes(module: str) -> tuple[str, ...]:
    return tuple(f"addons/{module}/static/{sub}/" for sub in SCOPE_SUBDIRS)


def is_hidden(rel: str) -> bool:

    return any(seg.startswith(".") for seg in rel.split("/"))


def module_files(module: str) -> list[str]:
    found = []
    for prefix in module_prefixes(module):
        base = ROOT / prefix
        if not base.exists():
            continue
        for path in base.rglob("*"):
            rel = path.relative_to(ROOT).as_posix()
            if is_hidden(rel):
                continue
            if path.is_file() and module_of(rel) == module:
                found.append(rel)
    return sorted(found)


@dataclass(frozen=True)
class ModuleVerdict:
    module: str
    ok: bool
    locked: int
    excepted: int
    regressed: list[str] = field(default_factory=list)
    stale: list[str] = field(default_factory=list)
    out_of_scope: list[str] = field(default_factory=list)
    resolved: list[str] = field(default_factory=list)
    unchecked: list[str] = field(default_factory=list)

    @property
    def coverage(self) -> float:
        total = self.locked + self.excepted + len(self.unchecked)
        return (self.locked / total * 100) if total else 100.0


@dataclass(frozen=True)
class Verdict:
    gate: str
    mode: str
    ok: bool
    modules: list[ModuleVerdict] = field(default_factory=list)

    @property
    def locked(self) -> int:
        return sum(m.locked for m in self.modules)

    @property
    def excepted(self) -> int:
        return sum(m.excepted for m in self.modules)

    @property
    def unchecked(self) -> int:
        return sum(len(m.unchecked) for m in self.modules)

    @property
    def coverage(self) -> float:
        total = self.locked + self.excepted + self.unchecked
        return (self.locked / total * 100) if total else 100.0


def evaluate_module(
    module: str,
    tally: dict[str, dict[str, int]],
    exceptions: list[str],
    files: list[str],
    mode: str,
    program: set[str] | None = None,
) -> ModuleVerdict:
    exempt = set(exceptions)
    errored = {p for p in tally if module_of(p) == module}
    uncompiled = set() if program is None else set(files) - program
    unchecked = sorted(uncompiled - exempt)

    regressed = sorted(errored - exempt)
    out_of_scope = sorted(e for e in exempt if module_of(e) != module)
    stale = sorted(
        e for e in exempt if module_of(e) == module and not (ROOT / e).exists()
    )
    resolved = sorted(
        e
        for e in exempt
        if module_of(e) == module
        and (ROOT / e).exists()
        and e not in errored
        and e not in uncompiled
    )

    excepted = len(exempt) - len(out_of_scope) - len(stale)
    locked = max(len(files) - excepted - len(unchecked), 0)

    ok = not (regressed or stale or out_of_scope or unchecked)
    if resolved and mode == "exact":
        ok = False
    return ModuleVerdict(
        module=module,
        ok=ok,
        locked=locked,
        excepted=excepted,
        regressed=regressed,
        stale=stale,
        out_of_scope=out_of_scope,
        resolved=resolved,
        unchecked=unchecked,
    )


def evaluate(
    gate: str,
    tally: dict[str, dict[str, int]],
    modules: tuple[str, ...],
    mode: str,
    program: set[str] | None = None,
) -> Verdict:
    verdicts = [
        evaluate_module(
            module,
            tally,
            read_exceptions(gate, module),
            module_files(module),
            mode,
            program,
        )
        for module in modules
    ]
    return Verdict(
        gate=gate,
        mode=mode,
        ok=all(v.ok for v in verdicts),
        modules=verdicts,
    )


def render(verdict: Verdict, tally: dict[str, dict[str, int]]) -> str:
    mark = "OK" if verdict.ok else "FAIL"
    total = verdict.locked + verdict.excepted + verdict.unchecked
    lines = [
        (
            f"[{mark}] {verdict.gate}: {verdict.locked} of {total} in-scope files "
            f"locked at zero ({verdict.coverage:.1f}% coverage), "
            f"{verdict.excepted} excepted, across {len(verdict.modules)} module(s)."
        ),
        "",
        (
            f"  {'module':<18}{'locked':>8}{'excepted':>10}{'unchecked':>11}"
            f"{'coverage':>10}"
        ),
    ]
    for mv in verdict.modules:
        flag = "" if mv.ok else "  FAIL"
        lines.append(
            f"  {mv.module:<18}{mv.locked:>8}{mv.excepted:>10}"
            f"{len(mv.unchecked):>11}{mv.coverage:>9.1f}%{flag}"
        )

    for mv in verdict.modules:
        lines.extend(_render_module_detail(mv, tally, verdict.mode))
    return "\n".join(lines)


def _render_module_detail(mv: ModuleVerdict, tally, mode: str) -> list[str]:
    lines = []
    if mv.regressed:
        lines.append(
            f"\n{mv.module}: {len(mv.regressed)} file(s) REGRESSED — in scope, "
            f"not excepted, and erroring. Fix them, or (if genuinely "
            f"unavoidable) add them via --update in the same commit so review "
            f"sees it:"
        )
        for path in mv.regressed:
            codes = ", ".join(
                f"{code}x{n}" for code, n in sorted(tally.get(path, {}).items())
            )
            lines.append(f"  {path}  [{codes}]")
    if mv.stale:
        lines.append(
            f"\n{mv.module}: {len(mv.stale)} exception(s) are STALE — the path "
            f"does not exist. A renamed file silently loses its exemption AND "
            f"its lock; repoint the entry at the new path, or drop it if the "
            f"file is gone:"
        )
        lines.extend(f"  {path}" for path in mv.stale)
    if mv.out_of_scope:
        lines.append(
            f"\n{mv.module}: {len(mv.out_of_scope)} exception(s) are OUT OF "
            f"SCOPE for this module's list and enforce nothing — move them to "
            f"the owning module's list, or remove them:"
        )
        lines.extend(f"  {path}" for path in mv.out_of_scope)
    if mv.resolved:
        verb = "must be removed" if mode == "exact" else "can be removed"
        lines.append(
            f"\n{mv.module}: {len(mv.resolved)} exception(s) are now CLEAN and "
            f"{verb} — rerun with --update to lock them in:"
        )
        lines.extend(f"  {path}" for path in mv.resolved)
    if mv.unchecked:
        lines.append(
            f"\n{mv.module}: {len(mv.unchecked)} file(s) are UNCHECKED — in "
            f"scope but absent from the tsc program, so their silence is not "
            f"evidence of anything. Widen the project's include/exclude to "
            f"cover them:"
        )
        if not mv.locked and not mv.excepted:
            lines.append(
                "  (the WHOLE module is missing — check the log was produced "
                "in this tree, not a copy elsewhere)"
            )
        lines.extend(f"  {path}" for path in mv.unchecked)
    return lines


def _leverage(codes: dict[str, int]) -> tuple[int, float]:
    total = sum(codes.values())
    ease = sum(CODE_EASE.get(c, DEFAULT_EASE) * n for c, n in codes.items()) / total
    return total, ease


def render_report(
    tally: dict[str, dict[str, int]],
    exceptions_by_module: dict[str, list[str]],
    regressed_by_module: dict[str, list[str]] | None,
    limit: int,
) -> str:

    regressed_by_module = regressed_by_module or {}
    blocking, excepted = [], []
    for module, entries in regressed_by_module.items():
        for path in entries:
            if codes := tally.get(path):
                total, ease = _leverage(codes)
                blocking.append((total * ease, total, ease, module, path, codes))
    for module, entries in exceptions_by_module.items():
        for path in entries:
            if codes := tally.get(path):
                total, ease = _leverage(codes)
                excepted.append((total * ease, total, ease, module, path, codes))
    blocking.sort(reverse=True)
    excepted.sort(reverse=True)

    def table(rows, cap):
        out = [f"{'score':>7} {'errs':>5} {'ease':>5}  {'module':<16} file"]
        for score, total, ease, module, path, codes in rows[:cap]:
            top = ", ".join(
                f"{c}x{n}" for c, n in sorted(codes.items(), key=lambda kv: -kv[1])[:3]
            )
            out.append(
                f"{score:7.1f} {total:5d} {ease:5.2f}  {module:<16} {path}  [{top}]"
            )
        return out

    lines = []
    if blocking:
        lines.append(
            f"{len(blocking)} REGRESSED file(s) — in scope, not excepted, and "
            f"erroring. These fail the gate; fix these first:"
        )
        lines.extend(table(blocking, limit))
        lines.append("")
    lines.append(
        f"{len(excepted)} exception(s) with errors, ranked by cleanup leverage "
        f"(errors x ease); showing {min(limit, len(excepted))}:"
    )
    lines.extend(table(excepted, limit))
    return "\n".join(lines)


UPDATE_HEADER = """\
# {gate} / {module}: files NOT yet clean under tsconfig.{gate}.json — the
# EXCEPTIONS to a default-deny gate, so this list may only shrink. Everything
# else in this module's scope ({scope}) is locked at zero, including files added
# after this list was written.
#
# Generated by tooling/typecheck/scope_gate.py --update. Do not hand-edit: run
# the gate, fix or exempt, regenerate. See tooling/typecheck/README.md.
"""


def report_candidates(text: str, limit: int, min_files: int = 20) -> int:

    errors = parse_log(text)
    program = parse_program_files(text)
    if not program:
        print(
            "error: no program file list in the log. Run tsc with --listFiles.",
            file=sys.stderr,
        )
        return EXIT_USAGE

    tally: dict[str, list[int]] = {}
    for path in program:
        if not path.endswith(CHECKED_SUFFIXES) or path.endswith(".d.ts"):
            continue
        match = MODULE_PATH_RE.match(path)
        if not match or match["module"] in SCOPED_MODULES:
            continue
        row = tally.setdefault(match["module"], [0, 0])
        row[0] += 1
        if path in errors:
            row[1] += 1

    big = {m: row for m, row in tally.items() if row[0] >= min_files}
    ranked = sorted(
        big.items(),
        key=lambda item: (-(item[1][0] - item[1][1]) / item[1][0], -item[1][0]),
    )
    print(
        f"Ungated modules with >= {min_files} compiled files, ranked by the "
        f"share that would lock"
    )
    print(f"  ({len(big)} of {len(tally)} ungated modules; the rest are smaller)")
    print(f"{'module':<28}{'files':>7}{'would lock':>13}{'excepted':>10}")
    for module, (total, dirty) in ranked[:limit]:
        locked = total - dirty
        print(
            f"{module:<28}{total:>7}{locked:>9} ({100 * locked // total:>3}%){dirty:>10}"
        )
    print(
        "\nA module that has to except most of itself teaches people to ignore "
        "the gate.\nAppend to SCOPED_MODULES only with the ratio in the commit "
        "message."
    )
    return EXIT_OK


def run(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="scope_gate.py",
        description="Default-deny type-check gate, one lock per module.",
    )
    parser.add_argument("gate", help="gate name; selects exceptions/<gate>/")
    parser.add_argument(
        "--log",
        required=True,
        help="path to captured tsc output, or - to read stdin",
    )
    parser.add_argument(
        "--module",
        action="append",
        metavar="NAME",
        help="restrict to one gated module (repeatable); default: all of "
        + ", ".join(SCOPED_MODULES),
    )
    parser.add_argument(
        "--mode",
        choices=("exact", "no-increase"),
        default="exact",
        help="exact (default): a newly-clean exception must be committed. "
        "no-increase: only regressions, stale and out-of-scope entries fail.",
    )
    parser.add_argument(
        "--prune",
        action="store_true",
        help="Repair the exception list WITHOUT exempting anything new: repoint "
        "an entry whose file was renamed (only when exactly one file in the "
        "module carries that basename), drop it when the file is gone, and drop "
        "an entry that no longer errors so the file locks at zero. --update "
        "cannot be used for this: it rewrites the list to EVERY erroring file, "
        "so the only sanctioned way to fix two stale paths was to exempt "
        "thirty-seven regressions with them.",
    )
    parser.add_argument(
        "--update",
        action="store_true",
        help="rewrite the exception lists from the log (the only way they move).",
    )
    parser.add_argument("--json", action="store_true", help="machine-readable verdict")
    parser.add_argument(
        "--report",
        action="store_true",
        help="rank remaining exceptions by cleanup leverage instead of gating",
    )
    parser.add_argument("--limit", type=int, default=20, help="--report row count")
    parser.add_argument(
        "--candidates",
        action="store_true",
        help="rank UNGATED modules by how much of each would lock, and exit",
    )
    parser.add_argument(
        "--min-files",
        type=int,
        default=20,
        help="--candidates: ignore modules smaller than this (default 20)",
    )
    args = parser.parse_args(argv)

    try:
        exceptions_path(args.gate, SCOPED_MODULES[0])
    except ValueError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return EXIT_USAGE

    modules = tuple(args.module or SCOPED_MODULES)
    unknown = [m for m in modules if m not in SCOPED_MODULES]
    if unknown:
        print(
            f"error: not a gated module: {', '.join(unknown)}. Gated modules "
            f"are {', '.join(SCOPED_MODULES)}; add one in SCOPED_MODULES.",
            file=sys.stderr,
        )
        return EXIT_USAGE

    if args.log == "-":
        text = sys.stdin.read()
    else:
        log = Path(args.log)
        if not log.exists():
            print(f"error: no such log: {args.log}", file=sys.stderr)
            return EXIT_USAGE
        text = log.read_text(encoding="utf-8", errors="replace")

    if args.candidates:
        return report_candidates(text, args.limit, args.min_files)

    tally = parse_log(text)
    program = parse_program_files(text)
    if not program:
        print(
            "error: no program file list in the log. Run tsc with --listFiles "
            "so the gate can tell a clean compile from one that never ran, and "
            "verify that every scoped file was actually compiled.",
            file=sys.stderr,
        )
        return EXIT_USAGE

    if args.prune:
        verdict = evaluate(args.gate, tally, modules, args.mode, program)
        rc = EXIT_OK
        for mv in verdict.modules:
            exceptions = read_exceptions(args.gate, mv.module)
            by_base: dict[str, list[str]] = {}
            for f in module_files(mv.module):
                by_base.setdefault(f.rsplit("/", 1)[-1], []).append(f)

            kept: list[str] = []
            for entry in exceptions:
                if entry in mv.resolved:
                    print(f"  drop (now clean, locks at zero): {entry}")
                    continue
                if entry in mv.stale:
                    candidates = by_base.get(entry.rsplit("/", 1)[-1], [])
                    # Exactly one, or not at all. Two files sharing a basename
                    # is a guess, and a guess here silently exempts the wrong
                    # file while leaving the intended one locked.
                    if len(candidates) == 1:
                        print(f"  repoint: {entry} -> {candidates[0]}")
                        kept.append(candidates[0])
                    elif not candidates:
                        print(f"  drop (file is gone): {entry}")
                    else:
                        print(
                            f"  KEPT {entry}: {len(candidates)} files share that "
                            f"basename, so the rename is ambiguous — repoint it "
                            f"by hand"
                        )
                        kept.append(entry)
                        rc = EXIT_DRIFT
                    continue
                kept.append(entry)

            if sorted(set(kept)) == sorted(exceptions):
                print(f"{mv.module}: nothing to prune")
                continue
            path = write_exceptions(args.gate, mv.module, sorted(set(kept)))
            print(
                f"wrote {path.relative_to(ROOT)}: {len(set(kept))} exception(s) "
                f"(was {len(exceptions)})"
            )
        return rc

    if args.update:
        for module in modules:
            keep = sorted(p for p in tally if module_of(p) == module)
            before = len(read_exceptions(args.gate, module))
            path = write_exceptions(args.gate, module, keep)
            delta = len(keep) - before
            sign = f"+{delta}" if delta > 0 else str(delta)
            print(
                f"wrote {path.relative_to(ROOT)}: {len(keep)} exception(s) "
                f"(was {before}, {sign})"
            )
        return EXIT_OK

    missing = [m for m in modules if not exceptions_path(args.gate, m).exists()]
    if missing:
        print(
            f"error: no exception list for {args.gate!r} module(s) "
            f"{', '.join(missing)}. Create them with:\n"
            f"  tooling/typecheck/scope_gate.py {args.gate} "
            f"--log {args.log} --update",
            file=sys.stderr,
        )
        return EXIT_USAGE

    verdict = evaluate(args.gate, tally, modules, args.mode, program)

    if args.report:
        print(
            render_report(
                tally,
                {m: read_exceptions(args.gate, m) for m in modules},
                {mv.module: mv.regressed for mv in verdict.modules},
                args.limit,
            )
        )
        return EXIT_OK

    if args.json:
        payload = asdict(verdict) | {
            "locked": verdict.locked,
            "excepted": verdict.excepted,
            "unchecked": verdict.unchecked,
            "coverage": round(verdict.coverage, 2),
        }
        for entry, mv in zip(payload["modules"], verdict.modules, strict=True):
            entry["coverage"] = round(mv.coverage, 2)
        print(json.dumps(payload, indent=2, sort_keys=True))
    else:
        print(render(verdict, tally))
    return EXIT_OK if verdict.ok else EXIT_DRIFT


if __name__ == "__main__":
    raise SystemExit(run())
