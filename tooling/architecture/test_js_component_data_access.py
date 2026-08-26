from pathlib import Path

import js_component_data_access as gate


def _write(root: Path, rel: str, source: str) -> None:
    path = root / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(source, encoding="utf-8")


class TestRootResolution:
    def test_it_points_at_the_components_tree(self):
        assert gate.COMPONENTS.is_dir(), gate.COMPONENTS
        assert gate.COMPONENTS.name == "components"

    def test_it_cites_an_accepted_record(self):
        matches = list((gate.ROOT / "doc" / "adr").glob(f"{gate.ADR}-*.md"))
        assert matches, gate.ADR
        assert "**Status:** Accepted" in matches[0].read_text(encoding="utf-8")


class TestDetection:
    def test_a_data_service_is_a_site(self, tmp_path):
        _write(tmp_path, "a/a.js", 'const o = useService("orm");')
        sites, _ = gate.measure(tmp_path)
        assert {s.key for s in sites} == {"a/a.js  orm"}

    def test_each_data_service_in_one_file_is_its_own_site(self, tmp_path):
        _write(tmp_path, "a/a.js", 'useService("orm"); useService("name");')
        sites, _ = gate.measure(tmp_path)
        assert {s.key for s in sites} == {"a/a.js  orm", "a/a.js  name"}

    def test_a_direct_rpc_is_a_site(self, tmp_path):
        _write(tmp_path, "a/a.js", "await rpc('/web/x', {});")
        sites, _ = gate.measure(tmp_path)
        assert {s.key for s in sites} == {"a/a.js  rpc"}

    def test_a_client_side_service_is_not_a_site(self, tmp_path):
        _write(
            tmp_path,
            "a/a.js",
            'useService("dialog"); useService("ui"); useService("notification");',
        )
        sites, _ = gate.measure(tmp_path)
        assert sites == set()

    def test_a_method_called_rpc_on_something_else_is_not_a_site(self, tmp_path):
        _write(tmp_path, "a/a.js", "this.orm.rpc('/x'); other.rpc();")
        sites, _ = gate.measure(tmp_path)
        assert sites == set()

    def test_a_name_that_merely_ends_in_rpc_is_not_a_site(self, tmp_path):
        _write(tmp_path, "a/a.js", "silentRpc('/x'); makeRpc();")
        sites, _ = gate.measure(tmp_path)
        assert sites == set()


class TestPin:
    def test_the_live_tree_matches_the_pin(self):
        sites, scanned = gate.measure()
        assert scanned, "no JS scanned — the gate would pass by finding nothing"
        assert {s.key for s in sites} == set(gate.PINNED)

    def test_every_pinned_entry_names_a_file_that_exists(self):
        for key in gate.PINNED:
            rel = key.split("  ")[0]
            assert (gate.COMPONENTS / rel).is_file(), key

    def test_check_passes_on_the_live_tree(self):
        assert gate.main(["--check"]) == 0

    def test_an_empty_tree_refuses_rather_than_passing(self, monkeypatch, tmp_path):
        empty = tmp_path / "components"
        empty.mkdir()
        monkeypatch.setattr(gate, "COMPONENTS", empty)
        assert gate.main(["--check"]) == 2

    def test_a_missing_tree_refuses(self, monkeypatch, tmp_path):
        monkeypatch.setattr(gate, "COMPONENTS", tmp_path / "gone")
        assert gate.main(["--check"]) == 2
