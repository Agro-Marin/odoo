#!/usr/bin/env python3
"""Every plural form must take its count as an argument, not spell it out.

`_pl(count, forms)` (`web/core/translation.js`) asks `Intl.PluralRules` which
category a count falls in for the active locale, and returns that form. The
categories are a property of the LOCALE, not of the number:

    en   "one" for 1
    fr   "one" for 0 and 1
    ru   "one" for 1, 21, 31, 41 ...

So a form whose text writes the number out instead of interpolating it is
correct only in the locales whose category for that number contains nothing
else. `formatX2many` shipped `{one: _t("1 record"), other: _t("%s records", n)}`,
which is right in English and silently wrong in Russian: twenty-one records
selected the "one" category, whose message has no placeholder to put 21 into,
and a one2many cell holding 21 records reported one. Fixed in 6e75d7d3234.

No English reading of any size can show it, which is why it survived a suite
that asserts the 1 and 2 cases. The rule that does catch it needs no locale and
no count: **a message handed to `_pl` must contain `%s`.**

That is deliberately stricter than "must not contain a digit". A form reading
"Only one left" spells its number as a word and fails in Russian the same way,
and a form that mentions no count at all ("Last item") is wrong for the same
reason. Requiring the placeholder is the one condition that makes a form safe
in every locale, and it costs a correct call site nothing.

A hard zero. There is no acceptable number of plural forms that cannot say how
many.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import asdict, dataclass
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from _repo_root import find_odoo_root

ROOT = find_odoo_root(Path(__file__).resolve(), tool="plural_forms")

SCAN_ROOTS = ("odoo/addons", "addons")

# Shipped source only. Vendored bundles carry their own translation machinery
# and are not ours; a test may legitimately build a malformed form as a fixture
# to assert what `_pl` does with it, which is not the same as shipping one.
REQUIRE_PART = "/static/src/"
SKIP_PARTS = ("/lib/", "/o_spreadsheet/", "/node_modules/")

_PL_CALL = re.compile(r"\b_pl\s*\(")
# a _t("...") or _t('...') message anywhere inside the call's arguments
_MESSAGE = re.compile(r"""_t\s*\(\s*(["'])((?:[^"'\\]|\\.)*?)\1""")


@dataclass(frozen=True)
class Finding:
    path: str
    line: int
    message: str

    def __str__(self) -> str:
        return f"  {self.path}:{self.line}\n      {self.message!r} takes no count"


def _call_body(text: str, start: int) -> tuple[str, int]:
    """The balanced parenthesised argument list beginning at `start`."""
    depth = 0
    for index in range(start, len(text)):
        char = text[index]
        if char == "(":
            depth += 1
        elif char == ")":
            depth -= 1
            if depth == 0:
                return text[start : index + 1], index + 1
    return text[start:], len(text)


def _sources(root: Path) -> list[Path]:
    files: list[Path] = []
    for rel in SCAN_ROOTS:
        tree = root / rel
        if not tree.is_dir():
            continue
        for path in tree.rglob("*.js"):
            spelled = f"/{path.relative_to(root).as_posix()}"
            if REQUIRE_PART not in spelled:
                continue
            if any(part in spelled for part in SKIP_PARTS):
                continue
            files.append(path)
    return files


def measure(root: Path = ROOT) -> tuple[list[Finding], int, int]:
    """Findings, files scanned, `_pl` call sites seen."""
    findings: list[Finding] = []
    files = _sources(root)
    calls = 0
    for path in files:
        text = path.read_text(encoding="utf8", errors="replace")
        if "_pl(" not in text:
            continue
        for call in _PL_CALL.finditer(text):
            body, _ = _call_body(text, call.end() - 1)
            calls += 1
            line = text[: call.start()].count("\n") + 1
            findings.extend(
                Finding(str(path.relative_to(root)), line, message.group(2))
                for message in _MESSAGE.finditer(body)
                if "%s" not in message.group(2)
            )
    return findings, len(files), calls


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--check", action="store_true", help="fail on any finding")
    parser.add_argument("--count", action="store_true", help="print the count only")
    parser.add_argument("--json", action="store_true", help="machine-readable")
    args = parser.parse_args(argv)

    findings, scanned, calls = measure()

    if not scanned:
        print(
            f"error: no JavaScript under {' or '.join(SCAN_ROOTS)} in {ROOT} -- "
            "the scan read nothing, which is not the same as finding nothing",
            file=sys.stderr,
        )
        return 2

    if args.count:
        print(len(findings))
        return 0
    if args.json:
        print(json.dumps([asdict(f) for f in findings], indent=2))
        return 0

    print("Plural forms that cannot say how many (hard zero)")
    print("=" * 72)
    for item in findings:
        print(item)
    print("-" * 72)
    # A vacuous pass is visible rather than silent: a run over a tree with no
    # `_pl` at all reports zero findings for a reason worth distinguishing from
    # a run that checked something.
    print(f"{scanned} file(s) scanned, {calls} _pl call site(s) checked.")
    if findings:
        print(f"{len(findings)} form(s) spell a number they cannot interpolate.")
        print(
            "\nA locale's plural category is not a number: `ru` puts 21 and 31 in "
            "'one'.\nGive every form a %s, including the singular."
        )
        return 1 if args.check else 0
    print("Every plural form takes its count. ✓")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
