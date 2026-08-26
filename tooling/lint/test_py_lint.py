import ast
import textwrap
from pathlib import Path

import pytest
from _repo_root import find_odoo_root

from . import py_lint

REPO = find_odoo_root(Path(__file__).resolve(), tool="test_py_lint")
PY_SCAN = REPO / "odoo" / "addons" / "test_lint" / "tests" / "_py_scan.py"


def _tuple_named(source: bytes, name: str) -> tuple[str, ...]:
    tree = ast.parse(source)
    for node in tree.body:
        if isinstance(node, ast.Assign) and any(
            isinstance(t, ast.Name) and t.id == name for t in node.targets
        ):
            return tuple(ast.literal_eval(node.value))
    raise AssertionError(f"{name} not found")


def test_the_corpus_exclusions_match_the_gates():
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


def test_a_gate_name_round_trips_through_the_baseline_glob():
    for scope in ("agromarin", "enterprise", "design-themes"):
        for rule in ("sql-injection", "n-plus-one-query", "noqa-rationale"):
            gate = py_lint.gate_name(rule, scope)
            suffix = f"_{scope}.json"
            recovered = gate + ".json"
            recovered = recovered[len("lint_") : -len(suffix)].replace("_", "-")
            assert recovered == rule, (scope, rule, gate)


def test_check_passes_at_the_floor_and_fails_above_it(tmp_path, monkeypatch):
    ratchet = py_lint._ratchet()
    monkeypatch.setattr(ratchet, "BASELINES_DIR", tmp_path)
    (tmp_path / "lint_sql_injection_probe.json").write_text('{"count": 2, "note": ""}')

    at_floor = [("sql-injection", "a.py", 1, ""), ("sql-injection", "b.py", 1, "")]
    assert py_lint.check(at_floor, "probe", "no-increase") == 0
    assert (
        py_lint.check(
            [*at_floor, ("sql-injection", "c.py", 1, "")], "probe", "no-increase"
        )
        == 1
    )
    assert py_lint.check(at_floor[:1], "probe", "no-increase") == 0
    assert py_lint.check(at_floor[:1], "probe", "exact") == 1


def test_a_rule_with_no_baseline_is_held_at_zero(tmp_path, monkeypatch):
    ratchet = py_lint._ratchet()
    monkeypatch.setattr(ratchet, "BASELINES_DIR", tmp_path)
    assert py_lint.check([], "probe", "no-increase") == 0
    assert (
        py_lint.check([("sql-injection", "a.py", 1, "")], "probe", "no-increase") == 1
    )
