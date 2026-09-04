from __future__ import annotations

import ast
import re
from pathlib import Path

import _ast_cache
from _repo_root import find_odoo_root

ROOT = find_odoo_root(Path(__file__).resolve(), tool="_doc_measures")

ARCH_DOCS = ROOT / "doc" / "architecture"


def gate_roster() -> list[str]:
    source = (
        ROOT / "tooling" / "architecture" / "test_every_gate_refuses_an_empty_tree.py"
    ).read_text(encoding="utf-8")
    roster = next(
        {key.value for key in node.value.keys}
        for node in ast.walk(ast.parse(source))
        if isinstance(node, ast.Assign)
        and getattr(node.targets[0], "id", "") == "GATES"
    )
    return sorted(roster)


def suite_methods(module: str) -> int:
    for tree in ("addons", "odoo/addons"):
        base = ROOT / tree / module / "tests"
        if base.is_dir():
            break
    else:
        raise FileNotFoundError(f"{module}/tests not found in either addon tree")
    return sum(
        sum(
            isinstance(node, ast.FunctionDef) and node.name.startswith("test")
            for node in ast.walk(_ast_cache.parse_file(path, errors="ignore"))
        )
        for path in sorted(base.rglob("*.py"))
    )


_UNITS = (
    "zero",
    "one",
    "two",
    "three",
    "four",
    "five",
    "six",
    "seven",
    "eight",
    "nine",
    "ten",
    "eleven",
    "twelve",
    "thirteen",
    "fourteen",
    "fifteen",
    "sixteen",
    "seventeen",
    "eighteen",
    "nineteen",
)
_TENS = (
    "_",
    "_",
    "twenty",
    "thirty",
    "forty",
    "fifty",
    "sixty",
    "seventy",
    "eighty",
    "ninety",
)


def number_word(value: int) -> str:
    if value < 20:
        return _UNITS[value]
    if value < 100:
        tens, unit = divmod(value, 10)
        return _TENS[tens] if not unit else f"{_TENS[tens]}-{_UNITS[unit]}"
    hundreds, rest = divmod(value, 100)
    head = f"{_UNITS[hundreds]}-hundred"
    return head if not rest else f"{head}-and-{number_word(rest)}"


NUMBER_WORDS = {number_word(value): value for value in range(1000)}
NUMBER_WORD_BY_VALUE = {value: word for word, value in NUMBER_WORDS.items()}

ANY_NUMBER = (
    r"(?:\d{1,4}(?:,\d{3})*|"
    + "|".join(sorted(NUMBER_WORDS, key=len, reverse=True))
    + r")"
)


def number_value(token: str) -> int:
    bare = token.replace(",", "")
    return int(bare) if bare.isdigit() else NUMBER_WORDS[token.lower()]


def flattened_pages() -> dict[str, str]:
    return {
        path.name: " ".join(path.read_text(encoding="utf-8").split())
        for path in sorted(ARCH_DOCS.glob("*.md"))
    }


def stated(pattern: str) -> list[tuple[str, re.Match[str]]]:
    rx = re.compile(pattern, re.IGNORECASE)
    return [
        (name, match)
        for name, flat in flattened_pages().items()
        for match in rx.finditer(flat)
    ]


_ORDINAL_UNITS = {
    "one": "first",
    "two": "second",
    "three": "third",
    "five": "fifth",
    "eight": "eighth",
    "nine": "ninth",
    "twelve": "twelfth",
}


def ordinal_word(value: int) -> str:
    word = number_word(value)
    head, _, tail = word.rpartition("-")
    ordinal = _ORDINAL_UNITS.get(tail) or (
        f"{tail[:-1]}ieth" if tail.endswith("y") else f"{tail}th"
    )
    return f"{head}-{ordinal}" if head else ordinal
