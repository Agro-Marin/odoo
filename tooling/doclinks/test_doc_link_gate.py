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
    def test_odoo_root_is_the_checkout_root(self):
        assert (gate.ODOO_ROOT / "odoo-bin").is_file()

    def test_this_file_lives_under_the_resolved_root(self):
        assert Path(__file__).resolve().is_relative_to(gate.ODOO_ROOT)

    def test_missing_marker_raises_instead_of_guessing_a_root(self):
        """A wrong root must abort, not silently scan the wrong tree."""
        with pytest.raises(SystemExit) as excinfo:
            find_odoo_root(Path("/nonexistent/deep/path"), tool="probe")
        assert "odoo-bin" in str(excinfo.value)

    def test_repo_root_differs_from_odoo_root_only_in_a_workspace(self):
        if gate.IN_WORKSPACE:
            assert gate.ODOO_ROOT.parents[1] == gate.REPO_ROOT
        else:
            assert gate.REPO_ROOT == gate.ODOO_ROOT


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


class TestBaseline:
    def test_baseline_sits_beside_the_gate(self):
        assert gate.DEFAULT_BASELINE_PATH.is_file()
        assert gate.DEFAULT_BASELINE_PATH.parent.parent == Path(gate.__file__).parent

    def test_baseline_loads_as_violation_keys(self):
        entries = gate.load_baseline(gate.DEFAULT_BASELINE_PATH)
        assert entries
        assert all(isinstance(key, tuple) and len(key) == 2 for key in entries)


class TestReferenceExtraction:
    def test_only_backticked_references_are_extracted(self):
        refs = gate._extract_refs("see `real/path.md` but not bare other.md\n")
        assert [raw for _, raw in refs] == ["real/path.md"]

    def test_anchors_are_stripped(self):
        assert gate._strip_anchor("guide.md#section") == "guide.md"
