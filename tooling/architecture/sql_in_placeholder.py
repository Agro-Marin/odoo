#!/usr/bin/env python3
"""``IN %s`` bound to a value, which psycopg3 cannot execute (ADR-0055).

psycopg2 adapted a Python tuple into the literal ``(1, 2, 3)`` before the
statement left the client, so ``WHERE id IN %s`` had a parenthesised list to
read by the time the server saw it. psycopg3 -- the only driver this fork uses
-- binds server-side: the placeholder reaches PostgreSQL as ``$N``, and
``IN $N`` is not valid SQL for ANY value type. Measured on this fork's cursor:

    cr.execute("... id IN %(x)s", {"x": (1, 2)})   SyntaxError near "$1"
    cr.execute("... id IN %(x)s", {"x": [1, 2]})   SyntaxError near "$1"
    execute_query(SQL("... id IN %(x)s", x=(1, 2)))            runs
    execute_query(SQL("... id IN %(x)s", x=[1, 2]))            SyntaxError

THE SPELLING IS NOT WRONG, THE CALLER IS. ``odoo.libs.sql.builder.SQL`` gives a
tuple argument its own branch: it expands into ``(%s, %s, ...)`` with one bound
parameter per element, and ``(NULL)`` when empty. So ``IN %s`` through ``SQL()``
with a tuple is CORRECT, and over a hundred sites in this tree depend on it. The
same text handed to ``cr.execute`` has no builder in front of it and is broken.
That is why this gate reads the call, not the string: a grep for ``IN %s``
answers with correct code roughly two times in three.

WHAT IT COUNTS. Two shapes, both decidable at the call site:

* A query literal passed DIRECTLY to ``cr.execute`` and friends. Nothing
  expands the placeholder there, so every ``IN %s`` in it is broken.
* An ``SQL(...)`` whose matching argument is provably NOT a tuple: a list
  display, a comprehension, ``list()``, ``sorted()``, ``.mapped()`` or a
  ``.ids`` attribute, each of which reaches the builder's generic branch and
  becomes one array parameter.

WHAT IT CANNOT SEE, stated plainly because the limit is real. A query assembled
into a VARIABLE and executed elsewhere is invisible to it, and that is the shape
of both bugs that prompted this gate: ``l10n_ec`` appended ``AND <col> in %(x)s``
to a where-string that ``account``'s sequence mixin executed two files away, and
``marin``'s year-over-year wizard built its conditions in a list before handing
the join to ``cr.execute``. Deciding those needs real dataflow. Flagging every
literal that is not inside an ``SQL()`` instead was tried and is WRONG: core's
own ``ir_ui_view._get_filter_xmlid_query`` returns the query text from one method
and builds it with ``SQL(query, res_ids=tuple(...))`` in another, which is
correct and would be reported. A gate whose findings include correct code is
read as broken and ignored, so this one reports less and means it. Those two
shapes are held by their tests instead.

WHAT IT DOES NOT COUNT, and must not. An ``SQL(...)`` argument it cannot resolve
-- a bare name, a parameter, an attribute -- is left alone. All forty-nine such
sites were read by hand when this gate was written and every one was a tuple.
Nor a literal that Python's own ``%`` operator formats before it is ever a
query: ``calendar_recurrence``'s CHECK constraint interpolates two tuples into
``weekday IN %s AND byday IN %s`` at class-definition time, producing SQL
literals, not placeholders.

Nor ``= ANY(%s)``, which is the other correct spelling and wants a LIST -- the
exact inverse container. Nor ``IN (SELECT ...)`` or ``IN %s`` filled with a
composed ``SQL`` object such as ``query.subselect()``: those are SQL text
spliced before the statement is sent, not bound values.
"""

from __future__ import annotations

import argparse
import ast
import json
import re
import sys
from dataclasses import asdict, dataclass
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from _repo_root import find_odoo_root, sibling_repos_root

ADR = "0055"

ROOT = find_odoo_root(Path(__file__).resolve(), tool="sql_in_placeholder")

SCOPE = ROOT / "odoo"

DEFAULT_ADDON = "core"

ALL_ADDONS = "addons"

#: Sibling checkouts, resolved beside the odoo one. Absent from a single-repo CI
#: run by construction, so asking for one there SKIPS rather than reporting zero
#: -- a count ratchet reads zero as an improvement it cannot verify.
SIBLING_SCOPES = ("enterprise", "agromarin")

#: Scopes `--addon` accepts. A tree absent from here is measured by nothing.
GOVERNED_ADDONS = (DEFAULT_ADDON, ALL_ADDONS, *SIBLING_SCOPES)

#: A literal is only SQL if it carries a keyword spelled in UPPERCASE.
#:
#: Case is the discriminator, and it is the right one for this tree. The regex
#: below matches the English word "in", and prose that also carries a lowercase
#: "from" or "select" is far commoner than SQL: three of the first findings were
#: `"...amounting in %(amount)s from %(company_name)s"`, `"...%s/%s in %ss"` and
#: `"...is present in view but is in select multi."`. Requiring a clause keyword
#: case-insensitively admits all three. Requiring one UPPERCASE rejects them,
#: and still accepts the two shapes that matter: a whole statement, and a bare
#: WHERE-clause FRAGMENT such as l10n_ec's `AND <col> in %(x)s`, appended to a
#: query built elsewhere -- which carries no SELECT and no FROM, so a
#: statement-shaped test would miss the very bug this gate was written for.
#:
#: `IN` is excluded from the set on purpose: it is the token being judged, so
#: counting it would make every match qualify itself.
SQL_KEYWORD = re.compile(
    r"\b(SELECT|INSERT|UPDATE|DELETE|WITH|FROM|WHERE|SET|VALUES|JOIN|HAVING"
    r"|GROUP BY|ORDER BY|AND|OR|ON|EXTRACT|COALESCE|DISTINCT|LIMIT|UNION|USING)\b"
)

IN_PLACEHOLDER = re.compile(r"\b(?:NOT\s+IN|IN)\s+%(?:\((\w+)\))?s", re.IGNORECASE | re.DOTALL)

#: Calls whose first argument is a query string with no builder in front of it.
RAW_EXECUTORS = frozenset(
    {"execute", "executemany", "execute_query", "execute_query_dict"}
)

BUILDER = "SQL"


def addon_src(addon: str = DEFAULT_ADDON) -> Path:
    if addon == DEFAULT_ADDON:
        return SCOPE
    if addon == ALL_ADDONS:
        return ROOT / "addons"
    if addon in SIBLING_SCOPES:
        return sibling_repos_root(ROOT) / addon
    return ROOT / "addons" / addon


@dataclass(frozen=True)
class Offence:
    file: str
    line: int
    kind: str
    what: str

    def __str__(self) -> str:
        return f"  {self.kind:14}  {self.file}:{self.line}  {self.what}"


def _display(path: Path) -> str:
    try:
        return str(path.relative_to(ROOT))
    except ValueError:
        return str(path)


def _is_test_path(path: Path) -> bool:
    return "tests" in path.parts or path.name.startswith("test_")


def iter_source_files(src: Path | None = None) -> list[Path]:
    return sorted(
        p
        for p in (SCOPE if src is None else src).rglob("*.py")
        if "__pycache__" not in p.parts and not _is_test_path(p)
    )


def _string_of(node: ast.AST) -> str | None:
    """The static text of a string expression, as far as it can be known."""
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    if isinstance(node, ast.JoinedStr):
        return "".join(
            v.value
            for v in node.values
            if isinstance(v, ast.Constant) and isinstance(v.value, str)
        )
    if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Add):
        return (_string_of(node.left) or "") + (_string_of(node.right) or "")
    return None


def _is_not_a_tuple(node: ast.AST) -> bool:
    """Whether an argument is PROVABLY a non-tuple sequence.

    Deliberately one-sided. Everything it cannot see through -- names,
    parameters, attributes other than ``.ids`` -- answers False and is left
    alone; see the module docstring on why an unresolvable argument must not be
    counted.
    """
    if isinstance(node, (ast.List, ast.ListComp, ast.SetComp, ast.GeneratorExp)):
        return True
    if isinstance(node, ast.Attribute) and node.attr == "ids":
        return True
    if isinstance(node, ast.Call):
        func = node.func
        if isinstance(func, ast.Name) and func.id in ("list", "sorted"):
            return True
        if isinstance(func, ast.Attribute) and func.attr in ("mapped", "keys"):
            return True
    return False


def _builder_argument(call: ast.Call, text: str, match: re.Match) -> ast.AST | None:
    """The argument that will fill this placeholder in an ``SQL(...)`` call."""
    name = match.group(1)
    if name:
        for kw in call.keywords:
            if kw.arg == name:
                return kw.value
        return None
    spots = [m.start() for m in re.finditer(r"%s", text)]
    here = text.find("%s", match.start())
    if here not in spots:
        return None
    index = spots.index(here)
    return call.args[1 + index] if 1 + index < len(call.args) else None


def measure(
    files: list[Path] | None = None,
    src: Path | None = None,
) -> list[Offence]:
    if files is None:
        files = iter_source_files(src)
        if not files:
            raise RuntimeError(
                f"no Python sources under {SCOPE if src is None else src} -- the "
                f"scan found nothing, which is not the same as finding nothing wrong"
            )
    found: list[Offence] = []
    for path in files:
        try:
            tree = ast.parse(path.read_bytes())
        except SyntaxError:
            continue
        display = _display(path)

        # Every string literal that is the first argument of an SQL(...) call:
        # those are judged per placeholder below, and every OTHER SQL literal in
        # the file is judged by the fact that no builder holds it.
        builder_literals: set[int] = set()
        for call in (n for n in ast.walk(tree) if isinstance(n, ast.Call)):
            func = call.func
            callee = func.attr if isinstance(func, ast.Attribute) else getattr(func, "id", "")
            if callee != BUILDER or not call.args:
                continue
            text = _string_of(call.args[0])
            if text is None or not SQL_KEYWORD.search(text):
                continue
            builder_literals.add(id(call.args[0]))
            for match in IN_PLACEHOLDER.finditer(text):
                arg = _builder_argument(call, text, match)
                if arg is not None and _is_not_a_tuple(arg):
                    found.append(
                        Offence(
                            display,
                            call.lineno,
                            "sequence",
                            f"{match.group(0).strip()} <- {ast.unparse(arg)[:60]}",
                        )
                    )

        for call in (n for n in ast.walk(tree) if isinstance(n, ast.Call)):
            func = call.func
            callee = func.attr if isinstance(func, ast.Attribute) else getattr(func, "id", "")
            if callee not in RAW_EXECUTORS or not call.args:
                continue
            arg = call.args[0]
            if id(arg) in builder_literals:
                continue
            text = _string_of(arg)
            if text is None or not SQL_KEYWORD.search(text):
                continue
            found.extend(
                Offence(display, call.lineno, "unbuilt", match.group(0).strip())
                for match in IN_PLACEHOLDER.finditer(text)
            )
    found.sort(key=lambda f: (f.file, f.line))
    return found


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--count", action="store_true", help="print the count only")
    parser.add_argument("--json", action="store_true", help="machine-readable")
    parser.add_argument("--top", type=int, default=25, help="0 for all")
    parser.add_argument(
        "--addon",
        default=DEFAULT_ADDON,
        help=(
            f"what to measure: {DEFAULT_ADDON} (default) is the odoo/ package, "
            f"{ALL_ADDONS} is the whole bundled-addons tree as one number, and "
            f"{' and '.join(SIBLING_SCOPES)} are sibling checkouts"
        ),
    )
    args = parser.parse_args(argv)

    if args.addon not in GOVERNED_ADDONS:
        print(
            f"error: {args.addon!r} is not a governed scope. Onboarding one is a "
            f"row in GOVERNED_ADDONS and its own baseline, not a flag: a floor "
            f"over an unscanned tree checks nothing.\n"
            f"       governed: {', '.join(GOVERNED_ADDONS)}",
            file=sys.stderr,
        )
        return 2

    src = addon_src(args.addon)
    if args.addon in SIBLING_SCOPES and not src.is_dir():
        print(
            f"SKIP: {args.addon} is not checked out beside {ROOT.name}; "
            f"its own architecture.yml pairs the two and runs this there.",
            file=sys.stderr,
        )
        return 0

    try:
        found = measure(src=src)
    except RuntimeError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2

    if args.count:
        print(len(found))
        return 0
    if args.json:
        print(json.dumps([asdict(f) for f in found], indent=2))
        return 0

    where = {DEFAULT_ADDON: "odoo/", ALL_ADDONS: "addons/"}.get(
        args.addon, f"{args.addon}/"
    )
    print(f"`IN %s` bound to a value (ADR-0055, {where})")
    print("=" * 72)
    shown = found if args.top == 0 else found[: args.top]
    for item in shown:
        print(item)
    if len(found) > len(shown):
        print(f"  ... and {len(found) - len(shown)} more (--top 0 for all)")
    print("-" * 72)
    by_kind = {k: sum(1 for f in found if f.kind == k) for k in ("unbuilt", "sequence")}
    print(f"\n{len(found)} site(s)   <- the ratcheted number")
    print(
        f"  no SQL() builder: {by_kind['unbuilt']}   "
        f"builder given a non-tuple: {by_kind['sequence']}"
    )
    suffix = "" if args.addon == DEFAULT_ADDON else f" --addon {args.addon}"
    name = (
        "sql_in_placeholder"
        if args.addon == DEFAULT_ADDON
        else f"sql_in_placeholder_{args.addon}"
    )
    print("\nRatchet it:")
    print(f"  python tooling/architecture/sql_in_placeholder.py --count{suffix} \\")
    print(f"      | xargs python tooling/ratchet/ratchet.py {name} --count")
    return 0


if __name__ == "__main__":
    sys.exit(main())
