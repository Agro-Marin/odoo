"""Tests for the field-widget ``props.record`` surface gate.

The analyzer tests are the ones that matter. This surface was first measured
with a grep, and the grep was wrong in both directions at once — sweeping
identifiers merely *named* ``record`` and sweeping test fixtures — so it
reported ``record.foo`` and ``record.int_field`` as members of
``RelationalRecord`` and inflated ``record.data`` by about a quarter. Every case
below is one of those mistakes, pinned.
"""

import json
import shutil
import subprocess
import sys
from pathlib import Path

import js_field_record_surface as gate
import pytest
from _repo_root import find_odoo_root

NODE = shutil.which("node")
needs_node = pytest.mark.skipif(not NODE, reason="node is not on PATH")


def _analyse(tmp_path, source):
    path = tmp_path / "w.js"
    path.write_text(source, encoding="utf-8")
    done = subprocess.run(
        ["node", str(gate.ANALYZER), str(path)],
        capture_output=True,
        text=True,
        check=True,
    )
    return json.loads(done.stdout.splitlines()[0])


class TestRootResolution:
    def test_repo_root_is_the_checkout_root(self):
        assert (gate.ROOT / "odoo-bin").is_file()

    def test_missing_marker_raises_instead_of_guessing_a_root(self):
        with pytest.raises(SystemExit) as excinfo:
            find_odoo_root(Path("/nonexistent/deep/path"), tool="probe")
        assert "odoo-bin" in str(excinfo.value)

    def test_the_contract_and_analyzer_exist(self):
        assert gate.CONTRACT.is_file(), gate.CONTRACT
        assert gate.ANALYZER.is_file(), gate.ANALYZER


class TestDeclaredSurface:
    def test_both_arrays_are_read(self):
        full, narrow = gate.declared_surface()
        assert {"data", "update", "model"} <= full
        assert narrow < full, "the narrow surface must be a strict subset"

    def test_a_missing_array_is_an_error(self, monkeypatch, tmp_path):
        stub = tmp_path / "field_record_contract.js"
        stub.write_text("export const OTHER = [];\n")
        monkeypatch.setattr(gate, "CONTRACT", stub)
        with pytest.raises(SystemExit):
            gate.declared_surface()


@needs_node
class TestBindingResolution:
    def test_a_read_on_props_record_counts(self, tmp_path):
        out = _analyse(tmp_path, "class W { f() { return this.props.record.resId; } }")
        assert out["members"] == ["resId"]

    def test_a_destructured_record_counts(self, tmp_path):
        out = _analyse(
            tmp_path,
            "function f(props) { const { record } = props; return record.isNew; }",
        )
        assert out["members"] == ["isNew"]

    def test_an_unrelated_identifier_named_record_is_not_counted(self, tmp_path):
        """THE regression: x2many row variables and callback parameters are
        called `record` too, and the grep counted every one of them."""
        out = _analyse(
            tmp_path,
            "function f(list) { return list.records.map((record) => record.data); }",
        )
        assert out["members"] == []
        assert out["unresolved"] >= 1, "and it is reported, not silently dropped"

    def test_own_value_and_sibling_reads_are_told_apart(self, tmp_path):
        """The whole question: a widget reading its own field can take a narrow
        handle; one naming a sibling cannot."""
        out = _analyse(
            tmp_path,
            "class W { f() {"
            " const a = this.props.record.data[this.props.name];"
            " const b = this.props.record.data.company_id;"
            " const c = this.props.record.data[someExpr];"
            " return [a, b, c]; } }",
        )
        assert out["ownValue"] == 1
        assert out["siblings"] == ["company_id"]
        assert out["dynamic"] == 1

    def test_a_literal_key_is_a_sibling_not_a_dynamic_read(self, tmp_path):
        out = _analyse(tmp_path, 'const x = props.record.data["partner_id"];')
        assert out["siblings"] == ["partner_id"] and out["dynamic"] == 0

    def test_a_widget_is_recognised_by_standardFieldProps(self, tmp_path):
        assert _analyse(tmp_path, "import { standardFieldProps } from 'x';")["isWidget"]
        assert not _analyse(tmp_path, "const props = {};")["isWidget"]

    def test_a_prop_named_sibling_is_a_sibling(self, tmp_path):
        """THE regression: `data[this.props.colorField]` is another field, named
        by an option. Counted as merely `dynamic`, it made `monetary`, `gauge`
        and `stat_info` look convertible when they never were."""
        out = _analyse(
            tmp_path, "const x = this.props.record.data[this.props.colorField];"
        )
        assert out["propSiblings"] == ["colorField"]
        assert out["dynamic"] == 0

    def test_props_name_is_still_the_own_field(self, tmp_path):
        """`props.name` is the widget's OWN field and must not be swept in."""
        out = _analyse(tmp_path, "const x = this.props.record.data[this.props.name];")
        assert out["propSiblings"] == [] and out["ownValue"] == 1

    def test_a_local_key_stays_undecidable(self, tmp_path):
        """`monetary` resolves `currencyField` from an option or a field attribute
        at runtime; this pass cannot decide it and must not guess."""
        out = _analyse(tmp_path, "const x = this.props.record.data[currencyField];")
        assert (
            out["dynamic"] == 1 and out["propSiblings"] == [] and out["siblings"] == []
        )


@needs_node
class TestLiveTree:
    def test_widgets_are_found(self):
        assert len(gate.widget_files()) > 50

    def test_no_test_file_is_measured(self):
        """The grep swept fixtures, which is how `record.int_field` became a
        member of RelationalRecord."""
        assert not [p for p in gate.widget_files() if "tests" in p.parts]

    def test_every_reached_member_is_declared(self):
        full, _ = gate.declared_surface()
        state = gate.measure()
        assert not set(state["members"]) - full, sorted(set(state["members"]) - full)

    def test_the_split_is_non_trivial_in_both_directions(self):
        """If either side reaches zero the classification has stopped working."""
        metrics = gate.measure()["metrics"]
        assert metrics["narrow"] > 0 and metrics["needs_record"] > 0
        assert metrics["narrow"] + metrics["needs_record"] <= metrics["widgets"]

    def test_the_three_buckets_do_not_overlap(self):
        """`undecidable` exists so a widget is never claimed as convertible on a
        key this pass could not read."""
        m = gate.measure()["metrics"]
        assert m["narrow"] + m["needs_record"] + m["undecidable"] <= m["widgets"]
        assert m["undecidable"] > 0, "the bucket is empty — monetary should be in it"

    def test_check_passes_on_the_live_tree(self):
        assert gate.main(["--check"]) == 0

    def test_an_empty_scan_refuses_to_pass(self, monkeypatch):
        monkeypatch.setattr(gate, "widget_files", list)
        assert gate.main(["--check"]) == 2

    def test_the_needs_record_worklist_is_derivable(self):
        """The point of the gate: the conversion list is produced, not guessed."""
        files = gate.measure()["needs_record_files"]
        assert files and len(files) == gate.measure()["metrics"]["needs_record"]


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-v"]))
