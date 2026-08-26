from pathlib import Path

import js_component_face as gate


class TestRootResolution:
    def test_it_points_at_the_components_tree(self):
        assert gate.COMPONENTS.is_dir(), gate.COMPONENTS

    def test_it_cites_an_accepted_record(self):
        matches = list((gate.ROOT / "doc" / "adr").glob(f"{gate.ADR}-*.md"))
        assert matches, gate.ADR
        assert "**Status:** Accepted" in matches[0].read_text(encoding="utf-8")


class TestFaceDetection:
    def test_a_face_is_the_sibling_module(self, tmp_path):
        (tmp_path / "foo").mkdir()
        (tmp_path / "foo.js").write_text("export {};", encoding="utf-8")
        assert gate.has_face("foo", tmp_path) is True

    def test_a_directory_without_the_sibling_has_none(self, tmp_path):
        (tmp_path / "foo").mkdir()
        assert gate.has_face("foo", tmp_path) is False

    def test_the_live_faces_are_the_ones_the_boundary_gate_would_find(self):
        import js_face_boundary as boundary

        faced = boundary.faced_directories()
        for directory in ("dropdown", "pager", "record_selectors"):
            assert gate.has_face(directory)
            assert f"components/{directory}" in faced


class TestReach:
    def _consumer(self, tmp_path: Path, rel: str, source: str) -> Path:
        path = tmp_path / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(source, encoding="utf-8")
        return tmp_path

    def test_a_deep_import_names_its_directory(self, tmp_path):
        root = self._consumer(
            tmp_path,
            "a/a.js",
            'import x from "@web/components/select_menu/select_menu";',
        )
        reached, scanned = gate.reached_from_outside([root])
        assert reached == {"select_menu"} and scanned == 1

    def test_a_face_import_names_the_same_directory(self, tmp_path):
        root = self._consumer(
            tmp_path, "a/a.js", 'import x from "@web/components/dropdown";'
        )
        reached, _ = gate.reached_from_outside([root])
        assert reached == {"dropdown"}

    def test_webs_own_modules_are_not_outside_consumers(self, tmp_path):
        root = self._consumer(
            tmp_path,
            "addons/web/static/src/views/v.js",
            'import x from "@web/components/checkbox/checkbox";',
        )
        reached, scanned = gate.reached_from_outside([root])
        assert reached == set() and scanned == 0

    def test_a_non_component_specifier_is_ignored(self, tmp_path):
        root = self._consumer(
            tmp_path, "a/a.js", 'import x from "@web/core/utils/hooks";'
        )
        reached, _ = gate.reached_from_outside([root])
        assert reached == set()


class TestPin:
    def test_the_live_tree_matches_the_pin(self):
        reached, scanned = gate.reached_from_outside()
        assert scanned, (
            "no consumer JS scanned — the gate would pass by finding nothing"
        )
        faceless = {d for d in reached if not gate.has_face(d)}
        assert faceless == set(gate.PINNED_FACELESS)

    def test_every_pinned_directory_exists_and_is_still_faceless(self):
        for directory in gate.PINNED_FACELESS:
            assert (gate.COMPONENTS / directory).is_dir(), directory
            assert not gate.has_face(directory), directory

    def test_check_passes_on_the_live_tree(self):
        assert gate.main(["--check"]) == 0

    def test_a_missing_tree_refuses(self, monkeypatch, tmp_path):
        monkeypatch.setattr(gate, "COMPONENTS", tmp_path / "gone")
        assert gate.main(["--check"]) == 2

    def test_no_consumers_refuses_rather_than_passing(self, monkeypatch, tmp_path):
        monkeypatch.setattr(gate, "CONSUMER_ROOTS", (tmp_path / "nothing",))
        assert gate.main(["--check"]) == 2
