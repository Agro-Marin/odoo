from pathlib import Path

import doc_link_gate as gate
import pytest
from _repo_root import find_odoo_root


class TestRootResolution:
    def test_repo_root_is_the_checkout_root(self):
        assert (gate.REPO_ROOT / "odoo-bin").is_file()

    def test_this_file_lives_under_the_resolved_root(self):
        assert Path(__file__).resolve().is_relative_to(gate.REPO_ROOT)

    def test_missing_marker_raises_instead_of_guessing_a_root(self):
        with pytest.raises(SystemExit) as excinfo:
            find_odoo_root(Path("/nonexistent/deep/path"), tool="probe")
        assert "odoo-bin" in str(excinfo.value)

    def test_scope_never_leaves_this_checkout(self):
        assert find_odoo_root(Path(__file__).resolve()) == gate.REPO_ROOT
        for glob in gate.DEFAULT_SCAN_GLOBS:
            assert not glob.startswith(("/", "..")), glob
        for path in gate._glob_files(gate.DEFAULT_SCAN_GLOBS, gate.DEFAULT_EXCLUDES):
            assert path.is_relative_to(gate.REPO_ROOT), path


class TestScanCoverage:
    def test_default_globs_match_a_nonzero_number_of_files(self):
        files = gate._glob_files(gate.DEFAULT_SCAN_GLOBS, gate.DEFAULT_EXCLUDES)
        assert files, (
            "doc_link_gate matched zero files — it would report success "
            "regardless of how many broken references exist"
        )

    def test_scan_reaches_this_repo_s_own_docs(self):
        files = gate._glob_files(gate.DEFAULT_SCAN_GLOBS, gate.DEFAULT_EXCLUDES)
        assert any(f.name == "CLAUDE.md" for f in files)

    def test_every_scanned_file_exists(self):
        files = gate._glob_files(gate.DEFAULT_SCAN_GLOBS, gate.DEFAULT_EXCLUDES)
        assert all(f.is_file() for f in files)

    def test_every_machine_doc_tree_is_covered_not_just_web_s(self):
        files = gate._glob_files(gate.DEFAULT_SCAN_GLOBS, gate.DEFAULT_EXCLUDES)
        scanned = {f.parent for f in files if f.parent.name == "machine_doc_v1"}
        on_disk = {p for p in gate.REPO_ROOT.glob("**/machine_doc_v1") if p.is_dir()}
        on_disk = {p for p in on_disk if "node_modules" not in p.parts}
        assert scanned == on_disk, f"unwatched machine_doc trees: {on_disk - scanned}"

    def test_every_architecture_document_is_covered(self):
        files = set(gate._glob_files(gate.DEFAULT_SCAN_GLOBS, gate.DEFAULT_EXCLUDES))
        on_disk = set((gate.REPO_ROOT / "doc" / "architecture").glob("**/*.md"))
        assert len(on_disk) >= 5, (
            f"the architecture set has shrunk to {len(on_disk)} files; if it "
            f"moved, point this test at its new home -- an empty glob would "
            f"make every assertion below vacuously true"
        )
        assert on_disk <= files, f"unwatched architecture docs: {on_disk - files}"

    def test_the_front_door_is_in_the_set_it_indexes(self):
        front_door = gate.REPO_ROOT / "doc" / "architecture" / "ARCHITECTURE.md"
        assert front_door.is_file(), f"front door not at {front_door}"
        assert not (gate.REPO_ROOT / "odoo" / "ARCHITECTURE.md").exists(), (
            "two front doors: the old location is back, so readers and gates "
            "can disagree about which one is current"
        )

    def test_the_adr_log_is_scanned_as_markdown_not_only_for_citations(self):
        files = set(gate._glob_files(gate.DEFAULT_SCAN_GLOBS, gate.DEFAULT_EXCLUDES))
        on_disk = set((gate.REPO_ROOT / "doc" / "adr").glob("*.md"))
        assert on_disk, "the ADR log has moved; this test is blind"
        assert on_disk <= files, f"unwatched ADRs: {on_disk - files}"

    def test_third_party_trees_are_excluded(self):
        files = gate._glob_files(gate.DEFAULT_SCAN_GLOBS, gate.DEFAULT_EXCLUDES)
        assert not [f for f in files if "node_modules" in f.parts]


class TestExcludeMatching:
    @pytest.mark.parametrize(
        "path",
        [
            "node_modules/ajv/README.md",
            "addons/web/node_modules/x/README.md",
        ],
    )
    def test_node_modules_is_excluded_at_any_depth(self, path):
        assert gate._glob_match(path, "**/node_modules/**")

    def test_a_similarly_named_directory_is_not_excluded(self):
        assert not gate._glob_match(
            "addons/node_modules_notes/x.md", "**/node_modules/**"
        )

    def test_a_file_named_like_the_directory_is_not_excluded(self):
        assert not gate._glob_match("doc/node_modules.md", "**/node_modules/**")

    def test_non_directory_patterns_still_use_fnmatch(self):
        assert gate._glob_match("doc/x.md", "doc/*.md")
        assert gate._glob_match("doc/sub/x.md", "doc/*.md")
        assert not gate._glob_match("other/x.md", "doc/*.md")


class TestBaseline:
    def test_baseline_sits_beside_the_gate(self):
        assert gate.DEFAULT_BASELINE_PATH.is_file()
        assert gate.DEFAULT_BASELINE_PATH.parent.parent == Path(gate.__file__).parent

    def test_baseline_loads_as_violation_keys(self):
        entries = gate.load_baseline(gate.DEFAULT_BASELINE_PATH)
        assert all(isinstance(key, tuple) and len(key) == 2 for key in entries)

    def test_baseline_is_empty_so_the_gate_can_block(self):
        assert gate.load_baseline(gate.DEFAULT_BASELINE_PATH) == set()
        assert gate.scan() == []


class TestReferenceResolution:
    def test_rooted_looking_but_source_relative_ref_resolves(
        self, tmp_path, monkeypatch
    ):
        monkeypatch.setattr(gate, "REPO_ROOT", tmp_path)
        src_dir = tmp_path / "addons" / "odoo"
        target = src_dir / "addons" / "web" / "doc.md"
        target.parent.mkdir(parents=True)
        target.write_text("x", encoding="utf-8")
        source = src_dir / "CLAUDE.md"
        source.write_text("see `addons/web/doc.md`\n", encoding="utf-8")
        assert gate._resolve_ref(source, "addons/web/doc.md") == target.resolve()

    def test_genuinely_rooted_ref_still_resolves_at_repo_root(
        self, tmp_path, monkeypatch
    ):
        monkeypatch.setattr(gate, "REPO_ROOT", tmp_path)
        target = tmp_path / "addons" / "web" / "doc.md"
        target.parent.mkdir(parents=True)
        target.write_text("x", encoding="utf-8")
        source = tmp_path / "deep" / "nested" / "CLAUDE.md"
        source.parent.mkdir(parents=True)
        assert (
            gate._resolve_ref(source, "addons/web/doc.md")
            == tmp_path / "addons/web/doc.md"
        )

    def test_a_ref_resolving_nowhere_is_still_a_violation(self, tmp_path, monkeypatch):
        monkeypatch.setattr(gate, "REPO_ROOT", tmp_path)
        source = tmp_path / "addons" / "odoo" / "CLAUDE.md"
        source.parent.mkdir(parents=True)
        assert gate._resolve_ref(source, "addons/web/absent.md") is None

    def test_absolute_ref_does_not_fall_through_to_relative(
        self, tmp_path, monkeypatch
    ):
        monkeypatch.setattr(gate, "REPO_ROOT", tmp_path)
        source = tmp_path / "sub" / "CLAUDE.md"
        source.parent.mkdir(parents=True)
        (source.parent / "doc.md").write_text("x", encoding="utf-8")
        assert gate._resolve_ref(source, "/doc.md") is None

    def test_ref_escaping_the_checkout_is_a_violation(self, tmp_path, monkeypatch):

        monkeypatch.setattr(gate, "REPO_ROOT", tmp_path / "repo")
        outside = tmp_path / "sibling" / "CLAUDE.md"
        outside.parent.mkdir(parents=True)
        outside.write_text("x", encoding="utf-8")
        source = tmp_path / "repo" / "doc" / "adr" / "README.md"
        source.parent.mkdir(parents=True)
        assert gate._resolve_ref(source, "../../../sibling/CLAUDE.md") is None

    def test_rooted_ref_cannot_climb_out_with_dotdot(self, tmp_path, monkeypatch):
        monkeypatch.setattr(gate, "REPO_ROOT", tmp_path / "repo")
        (tmp_path / "repo").mkdir()
        outside = tmp_path / "outside.md"
        outside.write_text("x", encoding="utf-8")
        source = tmp_path / "repo" / "CLAUDE.md"
        assert gate._resolve_ref(source, "/../outside.md") is None

    def test_in_repo_refs_still_resolve_after_the_guard(self, tmp_path, monkeypatch):
        monkeypatch.setattr(gate, "REPO_ROOT", tmp_path)
        target = tmp_path / "doc" / "guide.md"
        target.parent.mkdir(parents=True)
        target.write_text("x", encoding="utf-8")
        source = tmp_path / "addons" / "web" / "machine_doc_v1" / "MAP.md"
        source.parent.mkdir(parents=True)
        assert gate._resolve_ref(source, "doc/guide.md") == target.resolve()


class TestNextTargetRanksReality:
    def test_live_scan_is_the_default_source(self):
        import doc_link_next_target as nt

        live = nt._live_violations()
        keys = {(v["source_file"], v["raw_path"]) for v in live["violations"]}
        assert keys == {v.key() for v in gate.scan()}

    def test_live_violations_are_rankable(self):
        import doc_link_next_target as nt

        scores = nt.score_files(nt._live_violations())
        assert all(s.total_refs > 0 and 0 < s.avg_ease <= 1 for s in scores)


class TestReferenceExtraction:
    def test_only_backticked_references_are_extracted(self):
        refs = gate._extract_refs("see `real/path.md` but not bare other.md\n")
        assert [raw for _, raw in refs] == ["real/path.md"]

    def test_anchors_are_stripped(self):
        assert gate._strip_anchor("guide.md#section") == "guide.md"


class TestAdrCitations:
    def test_the_citation_form_is_recognised(self):
        assert gate.RE_ADR.findall("see ADR-0001 and ADR-0013") == ["0001", "0013"]

    def test_a_bare_number_is_not_a_citation(self):
        assert gate.RE_ADR.findall("0001 is not a citation") == []

    def test_a_partial_number_is_not_a_citation(self):
        assert gate.RE_ADR.findall("ADR-1 ADR-00011") == []

    def test_the_letters_placeholder_is_not_a_citation(self):
        assert gate.RE_ADR.findall("write it as ADR-NNNN") == []

    def test_existing_adrs_resolve(self):
        numbers = sorted(
            p.name[:4] for p in gate.ADR_DIR.glob("[0-9][0-9][0-9][0-9]-*.md")
        )
        assert numbers, "no ADRs on disk — the fixture this rests on is gone"
        for number in numbers:
            assert gate.adr_exists(number), number

    def test_a_missing_adr_does_not_resolve(self):
        assert not gate.adr_exists("9999")

    def test_resolution_does_not_depend_on_the_slug(self):
        first = min(gate.ADR_DIR.glob("[0-9][0-9][0-9][0-9]-*.md"))
        assert gate.adr_exists(first.name[:4])

    def test_the_tree_has_no_dangling_citations(self):
        assert [
            (v.source_file, v.line, v.raw_path) for v in gate.scan_adr_citations()
        ] == []

    def test_it_actually_scans_something(self):
        files = gate._glob_files(gate.ADR_SCAN_GLOBS, gate.DEFAULT_EXCLUDES)
        assert len(files) > 500
        cited = sum(
            len(gate.RE_ADR.findall(f.read_text(encoding="utf-8", errors="ignore")))
            for f in files
        )
        assert cited > 50, f"only {cited} citations found; the scan set has shrunk"

    def test_the_gates_that_cite_adrs_as_rationale_are_in_scope(self):
        scanned = {
            str(f.relative_to(gate.REPO_ROOT))
            for f in gate._glob_files(gate.ADR_SCAN_GLOBS, gate.DEFAULT_EXCLUDES)
        }
        assert "tooling/architecture/layer_check.py" in scanned
        assert "doc/architecture/ARCHITECTURE.md" in scanned

    def test_this_gate_plants_no_live_citation_of_its_own(self):
        source = Path(gate.__file__).read_text(encoding="utf-8")
        assert gate.RE_ADR.findall(source) == []
