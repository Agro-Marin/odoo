#!/usr/bin/env python3
"""Default-deny type-check gate, one lock per module.

Every ``.js``/``.ts`` under ``addons/<module>/static/{src,tests}`` of a gated
module is locked at zero errors. Files not yet clean are listed in
``exceptions/<gate>/<module>.txt``; that list may only shrink. This inverts the
allowlist model it replaces, and the inversion is the whole point:

- an allowlist enumerates what is *enforced*, so anything it fails to mention —
  a new file, a renamed file, a whole directory nobody got around to adding —
  is unenforced by default, silently;
- an exception list enumerates what is *exempt*, so the default for anything
  unmentioned is "must be clean". New files are gated from their first commit,
  and a rename cannot launder a file out of enforcement.

The predecessor allowlists demonstrated both failure modes: 448 of 687
``static/src`` files were already strictNullChecks-clean while only 129 were
locked, and ``ui/block/ui_service.js`` lost its noImplicitAny lock entirely by
moving to ``ui/ui_service.js`` — no gate noticed either.

Why per-module lists when only ``web`` is gated
-----------------------------------------------
``web`` is the only module locked today, but the layout is per-module so that
adding the next one is additive rather than a restructure: append it to
``SCOPED_MODULES``, generate ``exceptions/<gate>/<module>.txt``, done. It also
buys three things immediately — each lock is reviewable by its module's owner
instead of colliding in one shared file, ``--module`` gates one module locally
in isolation, and a misfiled entry (a ``mail`` path in ``web.txt``) becomes an
``out-of-scope`` failure instead of a silent no-op.

Five ways to fail, all drift-zero
---------------------------------
1. ``regressed`` — an in-scope file errors and is not excepted. The real gate.
2. ``stale`` — an excepted path does not exist. This is the rename hole: without
   it, moving a file deletes its lock and the gate stays green.
3. ``out-of-scope`` — an excepted path is outside the module whose list holds
   it, so the entry enforces nothing and only rots.
4. ``resolved`` — an excepted file is now clean. In the default ``exact`` mode
   this FAILS, telling you to commit the shorter list, so the win is locked in
   and can never slip back. Same reasoning as ``tooling/ratchet``'s exact mode.
5. ``unchecked`` — an in-scope file tsc never compiled. Its silence is not
   evidence of cleanliness, so counting it as locked inflates coverage with
   files nothing looked at. This is not hypothetical: ``exclude: ["**/l10n*"]``,
   meant for the ``l10n_*`` addons, also swallowed the eight web tests under
   ``static/tests/core/l10n/`` and ``static/tests/l10n/``, and the gate reported
   them locked for its entire life.

Usage
-----
    # CI: run tsc, then gate its output. --listFiles is required — it is what
    # makes failure 5 detectable, and it doubles as proof the compile ran.
    npx tsc -p tsconfig.strict.json --noEmit --listFiles > /tmp/strict.log 2>&1 || true
    tooling/typecheck/scope_gate.py strict --log /tmp/strict.log

    # One module, for a local loop.
    tooling/typecheck/scope_gate.py strict --log /tmp/strict.log --module web

    # Maintainer: regenerate the lists from the current state (the only way an
    # entry is added). Commit the diff — review sees what got exempted.
    tooling/typecheck/scope_gate.py strict --log /tmp/strict.log --update

    tooling/typecheck/scope_gate.py strict --log /tmp/strict.log --json
    tooling/typecheck/scope_gate.py strict --log /tmp/strict.log --report

``--report`` ranks the remaining exceptions by cleanup leverage
(errors x per-code ease) so "what do I fix next" has a mechanical answer. It
subsumes the retired leverage-ranking tool this gate replaced, and reads the
live tsc log rather than a second committed baseline that could drift from it.
"""

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
# Located by marker, not by counting parents — see _repo_root. Every exception
# entry is stored repo-relative against this, so a wrong root silently turns
# every locked file into a "stale" one.
ROOT = find_odoo_root(Path(__file__).resolve(), tool="scope_gate")
EXCEPTIONS_DIR = HERE / "exceptions"

# The gated modules. Committed here rather than passed on the command line so CI
# and a local run cannot silently disagree about what is enforced.
#
# Adding one is a two-step change: append it here, then generate its lists with
# --update in the same commit. Do NOT add a module without checking what its
# coverage would be first — measured 2026-07-29 under checkJs, the seven
# candidates behind web are far from clean, and a gate that has to except most
# of a module teaches people to ignore it:
#
#     module          files  strict-locked  noImplicitAny-locked
#     mail              595      169 (28%)             127 (21%)
#     bus                36       10 (28%)               5 (14%)
#     html_editor       336       81 (24%)              69 (21%)
#     html_builder      193       50 (26%)              33 (17%)
#     website           564      172 (31%)             158 (28%)
#     point_of_sale     328      162 (49%)              80 (24%)
#     spreadsheet       144       56 (39%)              15 (10%)
SCOPED_MODULES = ("web",)

# ``static/lib`` is deliberately outside the scope: vendored third-party code
# (bootstrap, luxon, pdfjs) plus hoot, whose types are the test harness's own.
SCOPE_SUBDIRS = ("src", "tests")

CHECKED_SUFFIXES = (".js", ".ts")

# What a ``--listFiles`` line can end with. Wider than CHECKED_SUFFIXES: the
# program also holds .d.ts ambients, which are not themselves gated.
PROGRAM_SUFFIXES = (".js", ".ts", ".jsx", ".tsx", ".json")

MODULE_PATH_RE = re.compile(
    r"^addons/(?P<module>[^/]+)/static/(?P<subdir>%s)/" % "|".join(SCOPE_SUBDIRS)
)

# tsc diagnostic line: ``path/to/file.js(12,34): error TS2532: message``.
# Anchored at start-of-line on purpose — an unanchored search also matches paths
# quoted inside another file's message text, which would attribute an error to
# the wrong file and fail a locked file that is actually clean.
ERROR_LINE_RE = re.compile(
    r"^(?P<path>[^(\s][^(]*?)\((?P<line>\d+),(?P<col>\d+)\): error (?P<code>TS\d+): "
)

# Exit codes (stable, for CI to branch on) — same contract as tooling/ratchet.
EXIT_OK = 0
EXIT_DRIFT = 1
EXIT_USAGE = 2

# Per-code cleanup ease in [0, 1], higher = more likely a local fix. Used only
# to rank --report; it steers attention and never affects the verdict.
CODE_EASE = {
    "TS18047": 1.0,  # 'x' is possibly 'null'
    "TS18048": 1.0,  # 'x' is possibly 'undefined'
    "TS2532": 1.0,  # object is possibly 'undefined'
    "TS2531": 1.0,  # object is possibly 'null'
    "TS2454": 0.9,  # used before being assigned
    "TS7006": 0.8,  # parameter implicitly has an 'any' type
    "TS7005": 0.8,  # variable implicitly has an 'any' type
    "TS7031": 0.8,  # binding element implicitly has an 'any' type
    "TS7034": 0.7,  # variable implicitly 'any[]' from no annotation
    "TS2554": 0.5,  # expected N arguments, but got M
    "TS2322": 0.4,  # type X is not assignable to type Y
    "TS2345": 0.3,  # argument of type X is not assignable
    "TS2339": 0.3,  # property does not exist on type
    "TS2353": 0.3,  # object literal may only specify known properties
}
DEFAULT_EASE = 0.5


def module_of(path: str) -> str | None:
    """The gated module a repo-relative path belongs to, or None if unscoped."""
    if not path.endswith(CHECKED_SUFFIXES) or path.endswith(".d.ts"):
        return None
    match = MODULE_PATH_RE.match(path)
    if not match or match["module"] not in SCOPED_MODULES:
        return None
    return match["module"]


def in_scope(path: str) -> bool:
    return module_of(path) is not None


def parse_log(text: str) -> dict[str, dict[str, int]]:
    """Map each errored path to its ``{code: count}`` tally.

    Paths are normalised to repo-relative POSIX form so a log produced with
    absolute paths (``tsc`` does this when given an absolute project path)
    compares equal to the committed exception entries.
    """
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
    """Repo-relative paths of every file in the program, from ``--listFiles``.

    ``tsc --listFiles`` prints one absolute path per line alongside the
    diagnostics, so a single run yields both halves of the verdict.

    A space is treated as evidence the line is prose rather than a path — but
    only when the path does not exist. Rejecting every spaced line outright
    dropped a real file named ``with space.js`` from the program, which the
    gate then reported as ``unchecked`` and failed on, with a message telling
    the operator to widen the tsconfig's include/exclude: a true failure with
    an untrue cause. Existence on disk settles it without letting prose in.
    """
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
    """True for a path any segment of which starts with a dot.

    TypeScript's own globbing excludes these: ``include: ["**/*.js"]`` in
    tsconfig.json does NOT match ``src/model/.__e.js``. So a dotfile is in this
    gate's scope while being absent from the program tsc builds, and the gate
    reports it as ``unchecked`` — correctly, by its own rules, but for a file
    that can never be checked and that a fresh CI checkout never even sees
    (``.gitignore`` line 1 is ``.*``).

    That combination made the gate fail on editor droppings in a developer's
    working tree while passing in CI, which inverts what a default-deny lock is
    for: it must be *stricter* locally than the thing it protects, never noisier
    about files the protected thing ignores. Matching tsc's own rule is the fix —
    not a new ignore list, which would be a second source of truth for what is
    in scope and would drift from the tsconfig the way every other duplicated
    scope in this tree has.
    """
    return any(seg.startswith(".") for seg in rel.split("/"))


def module_files(module: str) -> list[str]:
    """Every file the module's scope covers, as repo-relative paths."""
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
    """The result of gating one module's slice of a tsc log."""

    module: str
    ok: bool
    locked: int  # in-scope files enforced at zero
    excepted: int  # in-scope files currently exempt
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
    """The aggregate result over every gated module."""

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
    """Compare one module's tsc errors against its exception list. Pure."""
    exempt = set(exceptions)
    errored = {p for p in tally if module_of(p) == module}
    # A scoped file tsc never compiled cannot be "locked at zero" — it reports
    # no errors because nothing looked at it. Left unchecked this silently
    # inflates coverage, which is exactly what `exclude: ["**/l10n*"]` did to
    # the eight web tests under */core/l10n/ and */tests/l10n/.
    uncompiled = set() if program is None else set(files) - program
    # Only files the gate would otherwise CLAIM are reported: an already-excepted
    # file asserts nothing, and counting it in both buckets would double it in
    # the coverage denominator.
    unchecked = sorted(uncompiled - exempt)

    regressed = sorted(errored - exempt)
    # An entry filed under this module but pointing elsewhere enforces nothing:
    # the module whose scope actually contains it reads its own list, not this
    # one, so the lock would be silently absent from both.
    out_of_scope = sorted(e for e in exempt if module_of(e) != module)
    # A stale entry is in scope by name but absent from disk — i.e. renamed or
    # deleted. Checked before "resolved" so a moved file reads as a lost lock,
    # not as a fixed file.
    stale = sorted(
        e for e in exempt if module_of(e) == module and not (ROOT / e).exists()
    )
    # ``e not in uncompiled`` for the same reason ``stale`` is checked first: a
    # file nothing compiled is silent, not clean, and dropping its exception on
    # that basis would retire a lock the gate never actually verified.
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
            # Every single file missing is not an exclude bug; it is almost
            # always a log captured under a different root (a /tmp copy of the
            # tree), whose absolute paths no entry can match.
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
    """Rank the work by cleanup leverage: errors x average ease.

    Regressed files are listed FIRST and separately. They are what "what do I
    fix next" means when the gate is red — they block the build, while an
    excepted file merely sits on a list. Ranking only the exceptions omitted
    them by construction (a regression is, by definition, not excepted), so the
    one mode built to answer that question could not see the 14 files failing
    the strict lock.
    """
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

    tally = parse_log(text)
    program = parse_program_files(text)
    if not program:
        # The file list doubles as proof the compile happened. Without it a
        # broken invocation (bad config path, OOM, missing node_modules) is
        # indistinguishable from a clean program, and gating on that would let a
        # silently-broken CI step green-light every locked file.
        print(
            "error: no program file list in the log. Run tsc with --listFiles "
            "so the gate can tell a clean compile from one that never ran, and "
            "verify that every scoped file was actually compiled.",
            file=sys.stderr,
        )
        return EXIT_USAGE

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
        # A module with nothing to except still gets an empty file, so a missing
        # one means the lists were never generated for this gate — not that the
        # module is clean. Gating on that would be an accident either way.
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
