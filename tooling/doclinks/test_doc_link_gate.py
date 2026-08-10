"""Tests for the doc-link gate's root resolution and scan coverage.

The gate's worst failure is silent: anchored on the wrong root it matched no
globs, scanned **zero files, found zero violations and exited 0** while the tree
was full of broken references. Nothing caught it because the gate was untested
and its own tree was not in ``testpaths``. These tests exist mainly so that
failure mode cannot recur.
"""

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
        """A wrong root must abort, not silently scan the wrong tree."""
        with pytest.raises(SystemExit) as excinfo:
            find_odoo_root(Path("/nonexistent/deep/path"), tool="probe")
        assert "odoo-bin" in str(excinfo.value)

    def test_scope_never_leaves_this_checkout(self):
        # The gate used to climb to the workspace and scan sibling checkouts by
        # name. A framework fork can only verify its own tree.
        assert find_odoo_root(Path(__file__).resolve()) == gate.REPO_ROOT
        for glob in gate.DEFAULT_SCAN_GLOBS:
            assert not glob.startswith(("/", "..")), glob
        for path in gate._glob_files(gate.DEFAULT_SCAN_GLOBS, gate.DEFAULT_EXCLUDES):
            assert path.is_relative_to(gate.REPO_ROOT), path


class TestScanCoverage:
    def test_default_globs_match_a_nonzero_number_of_files(self):
        """THE regression: an empty match set is the silent-no-op signature."""
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
        # The scope was four globs over 24 files while SEVEN machine_doc_v1
        # directories existed, so four genuinely broken references sat in the
        # six it did not watch. Green meant "those four globs are clean", not
        # "this repo's docs are clean".
        files = gate._glob_files(gate.DEFAULT_SCAN_GLOBS, gate.DEFAULT_EXCLUDES)
        scanned = {f.parent for f in files if f.parent.name == "machine_doc_v1"}
        on_disk = {p for p in gate.REPO_ROOT.glob("**/machine_doc_v1") if p.is_dir()}
        on_disk = {p for p in on_disk if "node_modules" not in p.parts}
        assert scanned == on_disk, f"unwatched machine_doc trees: {on_disk - scanned}"

    def test_every_architecture_document_is_covered(self):
        # `test_architecture_doc.py` concatenates the whole set and asserts
        # against the blob, so which file a sentence sits in is presentational;
        # what holds the set together for a human is its relative links.
        #
        # None of them was checked. The only `doc/` entry in the scan globs was
        # `doc/*.md`, which reads like a deliberate one-level narrowing around
        # `doc/cla/` and in fact matched ZERO files -- `doc/` has no `.md` at
        # its top level at all. Widening surfaced 15 broken references, every
        # one a backticked bare filename that resolved only from the directory
        # the *other* half of the document lived in: the set was split across
        # `odoo/` and `doc/architecture/`. It is one flat directory now, which
        # is what makes a bare sibling filename the correct citation and this
        # glob the whole story -- no front-door special case any more.
        files = set(gate._glob_files(gate.DEFAULT_SCAN_GLOBS, gate.DEFAULT_EXCLUDES))
        on_disk = set((gate.REPO_ROOT / "doc" / "architecture").glob("**/*.md"))
        # A floor, not a count: the guard exists so an empty or relocated glob
        # cannot make the assertion below vacuously true, and pinning the exact
        # size would instead fail every time a view is added or retired. It
        # was `>= 10` and the set is 9 -- the findings page was deleted, being
        # a record of how each rule was arrived at rather than part of the
        # spec.
        assert len(on_disk) >= 5, (
            f"the architecture set has shrunk to {len(on_disk)} files; if it "
            f"moved, point this test at its new home -- an empty glob would "
            f"make every assertion below vacuously true"
        )
        assert on_disk <= files, f"unwatched architecture docs: {on_disk - files}"

    def test_the_front_door_is_in_the_set_it_indexes(self):
        # It lived in `odoo/` until 2026-08 -- a package-scoped location for a
        # repo-scoped document, which is what manufactured the cross-directory
        # links that rotted. Co-locating it is what retires them.
        front_door = gate.REPO_ROOT / "doc" / "architecture" / "ARCHITECTURE.md"
        assert front_door.is_file(), f"front door not at {front_door}"
        assert not (gate.REPO_ROOT / "odoo" / "ARCHITECTURE.md").exists(), (
            "two front doors: the old location is back, so readers and gates "
            "can disagree about which one is current"
        )

    def test_the_adr_log_is_scanned_as_markdown_not_only_for_citations(self):
        # `ADR_SCAN_GLOBS` already reaches the records, but only to resolve
        # `ADR-NNNN` citations. That grammar says nothing about the `.md` paths
        # an ADR cites in its Context and Enforcement sections, and those are
        # the ones that rot when a file moves under an immutable record.
        files = set(gate._glob_files(gate.DEFAULT_SCAN_GLOBS, gate.DEFAULT_EXCLUDES))
        on_disk = set((gate.REPO_ROOT / "doc" / "adr").glob("*.md"))
        assert on_disk, "the ADR log has moved; this test is blind"
        assert on_disk <= files, f"unwatched ADRs: {on_disk - files}"

    def test_third_party_trees_are_excluded(self):
        files = gate._glob_files(gate.DEFAULT_SCAN_GLOBS, gate.DEFAULT_EXCLUDES)
        assert not [f for f in files if "node_modules" in f.parts]


class TestExcludeMatching:
    """``**/<dir>/**`` must exclude that directory wherever it sits."""

    @pytest.mark.parametrize(
        "path",
        [
            "node_modules/ajv/README.md",  # top level — the broken case
            "addons/web/node_modules/x/README.md",  # nested — the case that worked
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
        # The fallback keeps fnmatch semantics deliberately, `*` spanning `/`
        # included — these are exclude patterns, where matching too much is the
        # safe direction and matching too little is the bug fixed above.
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
        # Scoped to this repo, there is nothing left to tolerate; doc_links.yml
        # is blocking on that basis.
        assert gate.load_baseline(gate.DEFAULT_BASELINE_PATH) == set()
        assert gate.scan() == []


class TestReferenceResolution:
    """The documented order must FALL THROUGH, not first-match-wins."""

    def test_rooted_looking_but_source_relative_ref_resolves(
        self, tmp_path, monkeypatch
    ):
        # `addons/odoo/CLAUDE.md` cites `addons/web/machine_doc_v1/TEST_TAGS.md`.
        # It starts with a rooted-looking segment but is relative to the citing
        # file. Step 2 used to `return None` on failure, so the gate reported a
        # file that exists — and printed the existing path while doing it.
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
        # A leading `/` means repo-root-anchored and nothing else; resolving it
        # relative to the source would silently accept the wrong file.
        monkeypatch.setattr(gate, "REPO_ROOT", tmp_path)
        source = tmp_path / "sub" / "CLAUDE.md"
        source.parent.mkdir(parents=True)
        (source.parent / "doc.md").write_text("x", encoding="utf-8")
        assert gate._resolve_ref(source, "/doc.md") is None

    def test_ref_escaping_the_checkout_is_a_violation(self, tmp_path, monkeypatch):
        """A sibling checkout is not this repo, even when it is on disk.

        The walk `.resolve()`s each candidate and only stops AFTER testing
        `current == REPO_ROOT`, so a `../../` ref climbed out of the tree.
        Measured on a real workstation: ``../../agromarin/CLAUDE.md`` cited from
        ``doc/adr/`` reported "No broken .md references found" because another
        git repository happened to sit next door — and the same ref in CI, where
        the repo stands alone, was a failure. A verdict that depends on what is
        outside the tree is the one thing this gate must not produce.
        """
        monkeypatch.setattr(gate, "REPO_ROOT", tmp_path / "repo")
        outside = tmp_path / "sibling" / "CLAUDE.md"
        outside.parent.mkdir(parents=True)
        outside.write_text("x", encoding="utf-8")
        source = tmp_path / "repo" / "doc" / "adr" / "README.md"
        source.parent.mkdir(parents=True)
        assert gate._resolve_ref(source, "../../../sibling/CLAUDE.md") is None

    def test_rooted_ref_cannot_climb_out_with_dotdot(self, tmp_path, monkeypatch):
        """The `/`-anchored branch needs the same guard as the walk."""
        monkeypatch.setattr(gate, "REPO_ROOT", tmp_path / "repo")
        (tmp_path / "repo").mkdir()
        outside = tmp_path / "outside.md"
        outside.write_text("x", encoding="utf-8")
        source = tmp_path / "repo" / "CLAUDE.md"
        assert gate._resolve_ref(source, "/../outside.md") is None

    def test_in_repo_refs_still_resolve_after_the_guard(self, tmp_path, monkeypatch):
        """Containment must not cost the legitimate walk-up resolutions."""
        monkeypatch.setattr(gate, "REPO_ROOT", tmp_path)
        target = tmp_path / "doc" / "guide.md"
        target.parent.mkdir(parents=True)
        target.write_text("x", encoding="utf-8")
        source = tmp_path / "addons" / "web" / "machine_doc_v1" / "MAP.md"
        source.parent.mkdir(parents=True)
        # Walks up from machine_doc_v1/ to the root before it matches.
        assert gate._resolve_ref(source, "doc/guide.md") == target.resolve()


class TestNextTargetRanksReality:
    """The ranker must answer "what is broken now", not "what was broken then"."""

    def test_live_scan_is_the_default_source(self):
        import doc_link_next_target as nt

        live = nt._live_violations()
        keys = {(v["source_file"], v["raw_path"]) for v in live["violations"]}
        assert keys == {v.key() for v in gate.scan()}

    def test_live_violations_are_rankable(self):
        # Measured on this tree: 72 of 478 baseline entries were already fixed
        # and 81 live violations were missing from it. Ranking live output is
        # what stops that drift from misdirecting the cleanup.
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
    """The citation form the repo actually uses, which the `.md` patterns miss.

    ``ARCHITECTURE.md`` names the *directory* ``doc/adr/`` and everything else
    writes a bare ADR number, so neither is a `.md` path and neither was
    checked. When ``doc/adr/`` was deleted this gate reported clean while 39
    citations dangled — only ``test_architecture_doc.py::test_adrs_exist``
    noticed, and only for one file.
    """

    def test_the_citation_form_is_recognised(self):
        assert gate.RE_ADR.findall("see ADR-0001 and ADR-0013") == ["0001", "0013"]

    def test_a_bare_number_is_not_a_citation(self):
        assert gate.RE_ADR.findall("0001 is not a citation") == []

    def test_a_partial_number_is_not_a_citation(self):
        # Four digits exactly: `ADR-1` and `ADR-00011` are not ADR numbers.
        assert gate.RE_ADR.findall("ADR-1 ADR-00011") == []

    def test_the_letters_placeholder_is_not_a_citation(self):
        """Docs describe the *form* as ADR-NNNN; that must not become work."""
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
        """Citations carry a number only; requiring the slug would make every
        ADR rename a tree-wide edit."""
        first = min(gate.ADR_DIR.glob("[0-9][0-9][0-9][0-9]-*.md"))
        assert gate.adr_exists(first.name[:4])

    def test_the_tree_has_no_dangling_citations(self):
        assert [
            (v.source_file, v.line, v.raw_path) for v in gate.scan_adr_citations()
        ] == []

    def test_it_actually_scans_something(self):
        """A glob typo would make an empty scan look like a clean tree."""
        files = gate._glob_files(gate.ADR_SCAN_GLOBS, gate.DEFAULT_EXCLUDES)
        assert len(files) > 500
        cited = sum(
            len(gate.RE_ADR.findall(f.read_text(encoding="utf-8", errors="ignore")))
            for f in files
        )
        assert cited > 50, f"only {cited} citations found; the scan set has shrunk"

    def test_the_gates_that_cite_adrs_as_rationale_are_in_scope(self):
        """`layer_check.py` justifies each enforced contract with an ADR; those
        12 citations were checked by nothing before."""
        scanned = {
            str(f.relative_to(gate.REPO_ROOT))
            for f in gate._glob_files(gate.ADR_SCAN_GLOBS, gate.DEFAULT_EXCLUDES)
        }
        assert "tooling/architecture/layer_check.py" in scanned
        assert "doc/architecture/ARCHITECTURE.md" in scanned

    def test_this_gate_plants_no_live_citation_of_its_own(self):
        """Its own prose must illustrate the form without citing a real ADR —
        otherwise documenting the rule creates work for the rule."""
        source = Path(gate.__file__).read_text(encoding="utf-8")
        assert gate.RE_ADR.findall(source) == []
