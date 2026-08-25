"""`py_lint.py` must answer what the in-odoo gate answers.

The tool exists so the sibling repositories can be measured at all, and the only
property that makes it worth having is that it runs the SAME checkers under the
SAME rules. Two things can drift: the corpus exclusions (a second copy of a
tuple) and the addon/framework split, which decides whether the facade rule
applies. Both are pinned here.

The addon/framework split is not hypothetical: getting it wrong reported 23
`orm-import` findings against the gate's 0, because the ORM's own modules import
`odoo.orm` and are entitled to.
"""

import ast
import textwrap
from pathlib import Path

import pytest

from . import py_lint

REPO = Path(__file__).resolve().parent.parent.parent
PY_SCAN = REPO / "odoo" / "addons" / "test_lint" / "tests" / "_py_scan.py"


def _tuple_named(source: bytes, name: str) -> tuple[str, ...]:
    """The value of a module-level tuple assignment, read without importing.

    `_py_scan` imports `lint_case`, which imports odoo; this suite is DB-free and
    stays that way.
    """
    tree = ast.parse(source)
    for node in tree.body:
        if isinstance(node, ast.Assign) and any(
            isinstance(t, ast.Name) and t.id == name for t in node.targets
        ):
            return tuple(ast.literal_eval(node.value))
    raise AssertionError(f"{name} not found")


def test_the_corpus_exclusions_match_the_gates():
    """A path the gate skips and the tool scans is a finding CI cannot reproduce."""
    gate = set(_tuple_named(PY_SCAN.read_bytes(), "_NOT_OURS"))
    tool = set(py_lint.NOT_OURS)
    assert gate <= tool, f"the tool scans what the gate skips: {sorted(gate - tool)}"


def test_a_file_under_a_manifest_is_in_an_addon(tmp_path):
    addon = tmp_path / "repo" / "addons" / "thing"
    (addon / "models").mkdir(parents=True)
    (addon / "__manifest__.py").write_text("{}")
    target = addon / "models" / "thing.py"
    target.write_text("x = 1")
    assert py_lint.in_an_addon(str(target))


def test_a_framework_file_is_not_in_an_addon(tmp_path):
    repo = tmp_path / "repo"
    (repo / "odoo" / "orm").mkdir(parents=True)
    (repo / "odoo-bin").write_text("#!/usr/bin/env python3\n")
    target = repo / "odoo" / "orm" / "fields.py"
    target.write_text("x = 1")
    assert not py_lint.in_an_addon(str(target))


def test_the_facade_rule_reaches_addon_code_and_not_the_framework(
    tmp_path, monkeypatch
):
    """The split above, end to end through the real checker."""
    repo = tmp_path / "repo"
    (repo / "odoo" / "orm").mkdir(parents=True)
    (repo / "odoo-bin").write_text("#!/usr/bin/env python3\n")
    (repo / "odoo" / "orm" / "models.py").write_text(
        "from odoo.orm.fields import Field\n"
    )
    addon = repo / "addons" / "thing"
    addon.mkdir(parents=True)
    (addon / "__manifest__.py").write_text("{}")
    (addon / "models.py").write_text("from odoo.orm.fields import Field\n")

    # Scanned through a RELATIVE root: `is_test_path` splits the whole path, and
    # pytest's own `tmp_path` is named `test_...`, which would make every file
    # look like a test and silence every rule scoped to non-test code. The suite
    # found that itself on the first run.
    monkeypatch.chdir(tmp_path)
    findings = py_lint.scan(["repo"])
    assert {path for rule, path, *_ in findings if rule == "orm-import"} == {
        "repo/addons/thing/models.py"
    }


@pytest.mark.parametrize(
    ("source", "rule"),
    [
        ('def f(self, t):\n    self.env.cr.execute(f"SELECT {t}")\n', "sql-injection"),
        (
            "def f(self, rs):\n    for r in rs:\n        self.search([])\n",
            "n-plus-one-query",
        ),
        ('raise UserError("plain")\n', "missing-gettext"),
        ("x = 1  # noqa: F401\n", "noqa-rationale"),
    ],
)
def test_each_checker_reaches_the_tool(tmp_path, monkeypatch, source, rule):
    addon = tmp_path / "repo" / "addons" / "thing"
    addon.mkdir(parents=True)
    (addon / "__manifest__.py").write_text("{}")
    (addon / "models.py").write_text(textwrap.dedent(source))
    monkeypatch.chdir(tmp_path)
    assert rule in {found for found, *_ in py_lint.scan(["repo"])}


def test_an_unparseable_file_is_reported_rather_than_skipped(tmp_path, monkeypatch):
    addon = tmp_path / "repo" / "addons" / "thing"
    addon.mkdir(parents=True)
    (addon / "__manifest__.py").write_text("{}")
    (addon / "broken.py").write_text("def f(:\n")
    monkeypatch.chdir(tmp_path)
    assert "unreadable-source" in {rule for rule, *_ in py_lint.scan(["repo"])}
