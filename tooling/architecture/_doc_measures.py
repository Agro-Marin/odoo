from __future__ import annotations

import ast
import re
from pathlib import Path

import _ast_cache
from _repo_root import find_odoo_root

ROOT = find_odoo_root(Path(__file__).resolve(), tool="_doc_measures")

ARCH_DOCS = ROOT / "doc" / "architecture"
WORKFLOW = ROOT / ".github" / "workflows" / "architecture.yml"

_GATE = r"python tooling/architecture/([\w.]+\.py)"
_STEP_ID = re.compile(r"^\s+id: \w+$", re.MULTILINE)
_INVOCATION = re.compile(
    r"tooling/architecture/([\w.]+)\.py((?:\s+--[\w-]+(?:\s+[\w.-]+)?)*)"
)
_SCOPE = re.compile(r"--(?:addon\s+([\w.-]+)|(cross-tree))")


def _workflow_text() -> str:
    return WORKFLOW.read_text(encoding="utf-8")


def workflow_gates() -> list[str]:
    return sorted(set(re.findall(_GATE, _workflow_text())))


def workflow_ratchets() -> list[str]:
    return sorted(set(re.findall(_GATE + r" --count", _workflow_text())))


def workflow_steps() -> list[str]:
    return _STEP_ID.split(_workflow_text())[1:]


def workflow_scoped_steps() -> set[tuple[str, str]]:
    found: set[tuple[str, str]] = set()
    for body in workflow_steps():
        run = body.split("run: |", 1)[1] if "run: |" in body else ""
        for match in _INVOCATION.finditer(run):
            scope = _SCOPE.search(match.group(2))
            if scope:
                found.add((match.group(1), scope.group(1) or "--cross-tree"))
    return found


def addon_scoped_gates() -> set[str]:
    return {gate for gate, scope in workflow_scoped_steps() if scope != "--cross-tree"}


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


_PIPE = re.compile(
    r"python tooling/architecture/([\w.]+\.py)([^|\n]*?)"
    r"(?:\s*\\\s*\n\s*\|\s*xargs python tooling/ratchet/ratchet\.py([^|\n]*))?$",
    re.MULTILINE,
)


def scoped_reproduce_rows() -> list[tuple[str, str]]:
    rows: list[tuple[str, str]] = []
    for body in workflow_steps():
        run = body.split("run: |", 1)[1] if "run: |" in body else ""
        if not _SCOPE.search(run):
            continue
        for match in _PIPE.finditer(run.replace("\\\n", "\\\n")):
            gate_args = " ".join(match.group(2).split())
            if "| tee" in match.group(2) or not (
                "--count" in gate_args or "--check" in gate_args
            ):
                continue
            ratchet = " ".join((match.group(3) or "").split())
            rows.append((f"{match.group(1)} {gate_args}".strip(), ratchet))
    return sorted(set(rows))


def self_test_only_gates() -> list[str]:
    source = (
        ROOT / "tooling" / "architecture" / "test_every_gate_refuses_an_empty_tree.py"
    ).read_text(encoding="utf-8")
    roster = next(
        {key.value for key in node.value.keys}
        for node in ast.walk(ast.parse(source))
        if isinstance(node, ast.Assign)
        and getattr(node.targets[0], "id", "") == "GATES"
    )
    in_ci = {gate.removesuffix(".py") for gate in workflow_gates()}
    missing = sorted(in_ci - roster)
    assert not missing, f"the empty-tree roster is short: {missing}"
    return sorted(roster - in_ci)
