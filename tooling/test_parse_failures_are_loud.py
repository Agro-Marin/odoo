"""A gate that cannot read a file must not report it as a file with nothing wrong.

Held at a hard zero, with no baseline JSON: this was born at zero the moment the
45 handlers it describes were converted, and CLAUDE.md §9.2 keeps a floor file
only for a gate that was driven down to zero rather than started there.

A handler that answers a failed read of a file on disk with `pass`, `continue`
or an empty `return` deletes the file from the gate's population. The gate then
reports one fewer finding, the ratchet reads that as progress and `--update`
invites someone to bank it, and the file that broke is the one nobody hears
about. Three ways a file can go unread were measured against the exact ruff.yml
commands over addons/ on 2026-09-02: a syntax error trips ruff's `invalid-syntax`
under any select; an undecodable file needs E902 named in the select, because
ruff warns on stderr and still exits 0; and a file that is merely unreadable to
one gate's own parser was, before this rule, caught by nothing at all.

Two tolerances are deliberate and both are narrow. A handler around
`ast.literal_eval` of a NODE -- not of a file -- is answering "this expression is
not a literal", which is a fact about the tree and not a read failure, so the
rule only looks at handlers whose `try` body touches the filesystem. And a
handler that turns the failure into a finding, a warning it raises, or a re-raise
is doing the reporting this rule exists to require: tooling/lint/py_lint.py is
the one file in the tree that takes it, emitting `unreadable-source` for the file
and going on to lint the rest. Everything else parses through
tooling/architecture/_ast_cache.py, whose SourceUnreadable names the path.

No tree in this workspace ships a fixture directory of intentionally broken
Python -- measured 2026-09-02, every one of the 10,864 .py files under odoo/,
7,746 under enterprise/, 2,143 under agromarin/ and 129 under design-themes/
parses, and all 1,576 __manifest__.py files literal_eval to a dict. A new
tolerance here is therefore hiding a file that did not exist before.
"""

from __future__ import annotations

import ast
from pathlib import Path

TOOLING = Path(__file__).resolve().parent

SKIP_DIRS = frozenset({"__pycache__", "node_modules", ".git", "vendored"})

FILE_READERS = frozenset(
    {"read_text", "read_bytes", "open", "parse_file", "literal_file"}
)

PARSERS = frozenset({"parse", "parse_source"})


def _is_silent(handler: ast.ExceptHandler) -> bool:
    if len(handler.body) != 1:
        return False
    only = handler.body[0]
    if isinstance(only, (ast.Pass, ast.Continue)):
        return True
    if not isinstance(only, ast.Return):
        return False
    if only.value is None:
        return True
    if isinstance(only.value, ast.Constant):
        return only.value.value is None
    if isinstance(only.value, (ast.List, ast.Tuple, ast.Set)):
        return not only.value.elts
    return isinstance(only.value, ast.Dict) and not only.value.keys


def _catches_a_parse_failure(handler: ast.ExceptHandler) -> bool:
    caught = handler.type
    if caught is None:
        return True
    members = caught.elts if isinstance(caught, ast.Tuple) else [caught]
    return any(
        ast.unparse(member).rsplit(".", 1)[-1]
        in ("SyntaxError", "UnicodeDecodeError", "ValueError")
        for member in members
    )


def _reads_a_file(body: list[ast.AST]) -> bool:
    for statement in body:
        for node in ast.walk(statement):
            if not isinstance(node, ast.Call):
                continue
            called = getattr(node.func, "attr", None) or getattr(node.func, "id", None)
            if called in FILE_READERS:
                return True
            if called in PARSERS and node.args:
                return True
            if called == "literal_eval" and _reads_a_file(list(node.args)):
                return True
    return False


def _sources() -> list[Path]:
    return sorted(
        path for path in TOOLING.rglob("*.py") if not SKIP_DIRS & set(path.parts)
    )


def silent_handlers() -> list[str]:
    found: list[str] = []
    for path in _sources():
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if not isinstance(node, ast.Try):
                continue
            if not _reads_a_file(node.body):
                continue
            for handler in node.handlers:
                if not _catches_a_parse_failure(handler):
                    continue
                if not _is_silent(handler):
                    continue
                found.append(
                    f"{path.relative_to(TOOLING)}:{handler.lineno}: "
                    f"{ast.unparse(handler.body[0])}"
                )
    return found


def test_no_gate_answers_an_unreadable_file_with_silence():
    offenders = silent_handlers()
    assert offenders == [], (
        "these handlers drop a file the gate could not read, so it counts as a "
        "file with no findings and lowers whatever ratchet it feeds. Parse "
        "through tooling/architecture/_ast_cache.py, which raises "
        "SourceUnreadable naming the path, or report the failure the way "
        "tooling/lint/py_lint.py does: " + ", ".join(offenders)
    )


def test_the_rule_sees_a_handler_planted_to_be_seen(tmp_path):
    planted = tmp_path / "planted.py"
    planted.write_text(
        "import ast\n"
        "def scan(paths):\n"
        "    for path in paths:\n"
        "        try:\n"
        "            tree = ast.parse(path.read_text())\n"
        "        except SyntaxError:\n"
        "            continue\n"
        "        yield tree\n",
        encoding="utf-8",
    )
    tree = ast.parse(planted.read_text(encoding="utf-8"))
    silent = [
        handler
        for node in ast.walk(tree)
        if isinstance(node, ast.Try) and _reads_a_file(node.body)
        for handler in node.handlers
        if _catches_a_parse_failure(handler) and _is_silent(handler)
    ]
    assert len(silent) == 1


def test_reporting_the_failure_is_the_sanctioned_tolerance():
    reporting = ast.parse(
        "try:\n"
        "    tree = ast.parse(path.read_text())\n"
        "except SyntaxError as exc:\n"
        "    findings.append(('unreadable-source', path, 1, str(exc)))\n"
    )
    node = reporting.body[0]
    assert _reads_a_file(node.body)
    assert _catches_a_parse_failure(node.handlers[0])
    assert not _is_silent(node.handlers[0])


def test_a_literal_eval_of_a_node_is_not_a_file_read():
    per_node = ast.parse(
        "try:\n    return ast.literal_eval(node)\nexcept ValueError:\n    return None\n"
    )
    assert not _reads_a_file(per_node.body[0].body)
