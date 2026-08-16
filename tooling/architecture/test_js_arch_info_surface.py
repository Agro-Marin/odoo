import json
import shutil
import subprocess
import sys
from pathlib import Path

import js_arch_info_surface as gate
import pytest
from _repo_root import find_odoo_root

NODE = shutil.which("node")
needs_node = pytest.mark.skipif(not NODE, reason="node is not on PATH")


def _analyse(tmp_path, source):
    path = tmp_path / "m.js"
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

    def test_the_contract_and_analyzer_exist_where_expected(self):
        assert gate.CONTRACT.is_file(), gate.CONTRACT
        assert gate.ANALYZER.is_file(), gate.ANALYZER


class TestDeclaredSurface:
    def test_both_arrays_are_read(self):
        owned, foreign = gate.declared_surface()
        assert "fieldNodes" in owned and "widgetNodes" in owned
        assert foreign

    def test_a_missing_array_is_an_error_not_an_empty_set(self, monkeypatch, tmp_path):
        stub = tmp_path / "arch_info.js"
        stub.write_text("export const SOMETHING_ELSE = [];\n")
        monkeypatch.setattr(gate, "CONTRACT", stub)
        with pytest.raises(SystemExit):
            gate.declared_surface()


@needs_node
class TestAnalyzer:
    def test_shorthand_properties_are_emitted(self, tmp_path):
        out = _analyse(tmp_path, "const f = () => { return { fieldNodes, xmlDoc }; };")
        assert {"fieldNodes", "xmlDoc"} <= set(out["emits"])

    def test_a_literal_assigned_then_returned_is_emitted(self, tmp_path):
        out = _analyse(
            tmp_path,
            "function p() { const archInfo = { rowGroupBys: [], widgets: {} };"
            " return archInfo; }",
        )
        assert {"rowGroupBys", "widgets"} <= set(out["emits"])

    def test_member_assignment_is_emitted(self, tmp_path):
        out = _analyse(tmp_path, "function p() { treeAttr.editable = 'top'; }")
        assert "editable" in out["emits"]

    def test_a_computed_key_is_not_invented(self, tmp_path):
        out = _analyse(tmp_path, "const o = { [dynamic]: 1 };")
        assert out["emits"] == []

    def test_reads_are_collected(self, tmp_path):
        out = _analyse(
            tmp_path, "const a = archInfo.columns; const b = archInfo?.limit;"
        )
        assert set(out["reads"]) == {"columns", "limit"}

    def test_a_template_scope_read_is_distinguished(self, tmp_path):
        out = _analyse(
            tmp_path,
            "const e = `__comp__.props.archInfo.fieldNodes[${id}]`;",
        )
        assert out["templateReads"] == ["fieldNodes"]

    def test_a_plain_string_without_comp_is_not_template_scope(self, tmp_path):
        out = _analyse(tmp_path, 'const msg = "archInfo.fieldNodes is missing";')
        assert out["templateReads"] == []

    def test_an_ordinary_read_is_not_counted_as_template_scope(self, tmp_path):
        out = _analyse(tmp_path, "const a = archInfo.fieldNodes;")
        assert out["reads"] == ["fieldNodes"] and out["templateReads"] == []


@needs_node
class TestLiveTree:
    def test_the_compiler_still_emits_into_template_source(self):
        state = gate.measure()
        assert {"fieldNodes", "widgetNodes"} <= set(state["template_reads"])

    def test_every_template_key_is_declared(self):
        owned, foreign = gate.declared_surface()
        state = gate.measure()
        undeclared = set(state["template_reads"]) - owned - foreign
        assert not undeclared, undeclared

    def test_every_view_type_agrees_with_its_parser(self):
        state = gate.measure()
        disagreeing = {
            name: info["unproduced"]
            for name, info in state["per_view"].items()
            if info["unproduced"]
        }
        assert not disagreeing, disagreeing

    def test_the_real_view_types_are_reached(self):
        state = gate.measure()
        for name in ("form", "list", "kanban", "graph", "pivot"):
            assert state["per_view"][name]["emitted"], f"{name} emitted nothing"

    def test_check_passes_on_the_live_tree(self):
        assert gate.main(["--check"]) == 0

    def test_an_empty_template_scan_refuses_to_pass(self, monkeypatch):
        monkeypatch.setattr(
            gate, "measure", lambda: {"template_reads": {}, "per_view": {}}
        )
        assert gate.main(["--check"]) == 2


class TestCrossViewReads:
    def test_every_exception_carries_a_reason(self):
        for directory, keys in gate.CROSS_VIEW_READS.items():
            for key, reason in keys.items():
                assert reason.strip(), f"{directory}.{key} has no rationale"

    def test_every_excepted_directory_exists(self):
        for directory in gate.CROSS_VIEW_READS:
            assert (gate.VIEWS / directory).is_dir(), directory

    @needs_node
    def test_an_exception_that_stopped_being_needed_is_visible(self):

        state = gate.measure()
        for directory, keys in gate.CROSS_VIEW_READS.items():
            read = set(state["per_view"][directory]["read"])
            assert set(keys) <= read, (
                f"views/{directory}/ no longer reads {sorted(set(keys) - read)} — "
                "drop the CROSS_VIEW_READS entry"
            )


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-v"]))
