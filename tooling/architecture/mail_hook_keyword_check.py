"""Gate the *keywords* the mail framework passes to hooks its addons override.

``mail`` is not an application, it is a framework: ``mixin.mail.thread`` and
``mixin.mail.activity`` are injected into business models across every repo, and
their ``_notify_*`` / ``_message_*`` / ``_track_*`` / ``_mail_*`` methods are
extension points that dozens of addons override. Adding a parameter to one of
those signatures is therefore a cross-repo change, and the compiler that would
have caught it does not exist in Python.

**The gap it closes.** On 2026-08-17 ``28ed9db3341`` added a ``tracking_values``
keyword to ``mixin.mail.thread._notify_by_email_prepare_rendering_context`` and
passed it from ``_notify_by_email_prepare``. Six modules override that hook --
``project``, ``crm``, ``account``, ``account_peppol``, ``base_order`` and
``enterprise/hr_appraisal`` -- and none of their signatures moved, so every
notified create in them raised::

    TypeError: ProjectTask._notify_by_email_prepare_rendering_context()
               got an unexpected keyword argument 'tracking_values'

One run of the dependent ring measured ``1 failed, 129 errors of 1654`` before the
fix and ``57 failed, 0 errors of 2085`` after (``e4bb93b8ee4``) -- 431 more tests
merely *reached*, because the TypeErrors were aborting whole classes. And it
merged green: ``/mail,/test_mail`` cannot see it, because neither module overrides
the hook -- ``mail`` declares it once and calls it once, and ``test_mail`` only
calls it from tests. That is the whole point -- **a framework's own suite cannot
reach the implementations of its extension points.** Run against that commit this
gate names all five community overrides; against the fixed tree it reports zero.

**What is checked.** For every hook ``mail`` defines under ``addons/mail/models``
and calls *by keyword* from its own code, every declaration of that hook must be
able to accept those keywords -- the 131 overrides outside ``mail`` and the
redeclarations inside it alike, since ``discuss.channel`` overrides the mixin from
within the framework directory and a stale signature there raises exactly the same
TypeError. A declaration that spells ``**kwargs`` absorbs anything and is not a
finding.

**What is deliberately not checked, and what is simply not covered.**

*Positional parameters, at all.* This is the deliberate one. ``_track_subtype``'s
base spells its parameter ``initial_values`` and all 29 overrides across the four
repos spell it ``init_values`` -- every call site passes it positionally, so the
name is private to the override and the divergence is harmless. A rule that
compared parameter *names* would report 37 findings in the community tree alone,
every one of them noise, which is how a gate gets switched off. Only keywords the
framework actually passes are counted.

The cost of that choice is real and is not covered: **a base that gains a
*required positional* parameter breaks every override, and this gate is blind to
it.** Nothing here would have caught that variant of ``28ed9db3341``.

*The reverse direction.* An override that forwards a keyword to ``super()`` which
the base has since dropped raises the same TypeError from the other side. Also
uncovered; it needs the call-site analysis this gate does not do.

*Same-named methods on unrelated models.* The base must be defined in
``addons/mail/models`` and the keyword must be one ``mail`` itself passes. A
``_message_foo`` invented by two addons that never talk to each other is not a
contract and is not measured.

*Tests.* An override in a ``tests/`` directory is a fixture, free to take whatever
shape its test needs.

**A contract, not a ratchet.** The tree measures zero and there is no reading of
this number under which a non-zero value is acceptable: a keyword an override
cannot accept is a ``TypeError`` waiting for the right record to be saved. It has
no baseline for the same reason ``layer_check``'s contracts have none.

**Cross-repo.** Overrides live in ``enterprise/`` and ``agromarin/`` too --
``hr_appraisal`` was the sixth. Community CI checks out this repo alone and so
measures the community overrides; the siblings pass ``--roots`` to cover their
own, the way ``naming_vocabulary`` and ``js_public_surface`` already do.

Usage::

  python tooling/architecture/mail_hook_keyword_check.py             # report
  python tooling/architecture/mail_hook_keyword_check.py --check     # CI
  python tooling/architecture/mail_hook_keyword_check.py --count
  python tooling/architecture/mail_hook_keyword_check.py --json
  python tooling/architecture/mail_hook_keyword_check.py --roots ../enterprise
"""

import argparse
import ast
import json
import sys
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from _repo_root import find_odoo_root

ADR = "unrecorded"

ROOT = find_odoo_root(Path(__file__).resolve(), tool="mail_hook_keyword_check")

FRAMEWORK_DIR = Path("addons/mail/models")

FRAMEWORK_CALLER_DIR = Path("addons/mail")

HOOK_PREFIXES = ("_notify", "_message", "_mail_", "_track")

SCAN_ROOTS = ("addons", "odoo/addons")


@dataclass(frozen=True)
class Finding:
    hook: str
    path: str
    line: int
    missing: tuple[str, ...]

    def __str__(self) -> str:
        kws = ", ".join(self.missing)
        return f"{self.path}:{self.line}  {self.hook}() cannot accept {kws}"


def _python_files(roots: list[Path]) -> list[Path]:
    files: list[Path] = []
    for root in roots:
        if root.is_file():
            files.append(root)
        elif root.is_dir():
            files.extend(p for p in root.rglob("*.py") if "node_modules" not in p.parts)
    return sorted(files)


def _rel(path: Path) -> str:
    try:
        return str(path.relative_to(ROOT))
    except ValueError:
        return str(path)


def _params(fn: ast.FunctionDef | ast.AsyncFunctionDef) -> set[str]:
    a = fn.args
    return {x.arg for x in a.posonlyargs + a.args + a.kwonlyargs}


def _methods(tree: ast.AST):
    for node in ast.walk(tree):
        if isinstance(node, ast.ClassDef):
            for fn in node.body:
                if isinstance(fn, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    yield fn


def measure(
    roots: list[Path] | None = None,
    *,
    framework_dir: Path | None = None,
    caller_dir: Path | None = None,
) -> list[Finding]:
    roots = roots or [ROOT / r for r in SCAN_ROOTS]
    framework_dir = framework_dir or ROOT / FRAMEWORK_DIR
    caller_dir = caller_dir or ROOT / FRAMEWORK_CALLER_DIR

    trees: dict[Path, ast.AST] = {}
    for path in _python_files(roots):
        try:
            trees[path] = ast.parse(path.read_text(errors="ignore"))
        except SyntaxError:
            continue

    base_hooks: dict[str, set[str]] = defaultdict(set)
    overrides: dict[str, list[tuple[Path, int, set[str], bool]]] = defaultdict(list)
    for path, tree in trees.items():
        in_framework = path.is_relative_to(framework_dir)
        for fn in _methods(tree):
            if not fn.name.startswith(HOOK_PREFIXES):
                continue
            if in_framework:
                base_hooks[fn.name] |= _params(fn)
            overrides[fn.name].append(
                (path, fn.lineno, _params(fn), fn.args.kwarg is not None)
            )

    if not base_hooks:
        raise SystemExit(
            f"mail_hook_keyword_check: no hooks found under {_rel(framework_dir)} — "
            "the scan found no inputs; refusing to report 0 findings."
        )

    keywords: dict[str, set[str]] = defaultdict(set)
    for path, tree in trees.items():
        if not path.is_relative_to(caller_dir):
            continue
        for node in ast.walk(tree):
            if (
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Attribute)
                and node.func.attr in base_hooks
            ):
                keywords[node.func.attr].update(
                    kw.arg for kw in node.keywords if kw.arg
                )

    if not any(keywords.values()):
        raise SystemExit(
            f"mail_hook_keyword_check: {_rel(caller_dir)} passes no keyword to any "
            "of its own hooks; refusing to report 0 findings."
        )

    findings: list[Finding] = []
    for hook, declared in base_hooks.items():
        used = keywords.get(hook, set()) & declared
        if not used:
            continue
        for path, line, params, absorbs in overrides.get(hook, ()):
            if absorbs or "tests" in path.parts:
                continue
            missing = used - params
            if missing:
                findings.append(Finding(hook, _rel(path), line, tuple(sorted(missing))))
    return sorted(findings, key=lambda f: (f.path, f.line, f.hook))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--check", action="store_true", help="CI mode: exit 1 on any finding"
    )
    parser.add_argument("--count", action="store_true", help="print the count only")
    parser.add_argument("--json", action="store_true", help="machine-readable")
    parser.add_argument("--roots", nargs="+", help="extra trees to scan for overrides")
    args = parser.parse_args(argv)

    roots = [ROOT / r for r in SCAN_ROOTS]
    if args.roots:
        roots += [Path(r).resolve() for r in args.roots]
    findings = measure(roots)

    if args.count:
        print(len(findings))
        return 0
    if args.json:
        print(json.dumps([f.__dict__ for f in findings], indent=2, default=list))
        return 1 if (args.check and findings) else 0

    print("mail hook keyword surface")
    print("=" * 72)
    for finding in findings:
        print(f"  {finding}")
    if not findings:
        print("  every override of a mail hook accepts the keywords mail passes it. ✓")
    print("-" * 72)
    print(f"scanned: {', '.join(_rel(r) for r in roots)}")
    print(f"findings: {len(findings)}")
    if findings:
        print(
            "\nEach one raises TypeError the first time that model is notified.\n"
            "Add the parameter to the override and forward it to super()."
        )
    return 1 if (args.check and findings) else 0


if __name__ == "__main__":
    raise SystemExit(main())
