"""Tests for the vendored-library gate's anchoring and manifest contract."""

from pathlib import Path

import check_vendored_libs as gate
import pytest


class TestRootResolution:
    def test_odoo_root_is_the_checkout_root(self):
        assert (gate.ODOO_ROOT / "odoo-bin").is_file()

    def test_lib_dir_resolves_to_the_vendored_tree(self):
        assert gate.LIB_DIR.is_dir()
        assert gate.LIB_DIR == gate.ODOO_ROOT / "addons/web/static/lib"

    def test_missing_marker_raises_instead_of_guessing(self):
        # Shares tooling/_repo_root now rather than carrying its own copy.
        with pytest.raises(SystemExit) as excinfo:
            gate.find_odoo_root(Path("/nonexistent/deep/path"), tool="probe")
        assert "odoo-bin" in str(excinfo.value)


class TestManifest:
    def test_manifest_sits_in_the_vendored_tree(self):
        assert gate.MANIFEST.is_file()

    def test_manifest_loads_and_is_nonempty(self):
        """An empty manifest would make --drift pass by checking nothing."""
        assert gate._load_manifest()

    def test_every_pinned_library_names_a_version(self):
        libs = gate._load_manifest()
        entries = {k: v for k, v in libs.items() if isinstance(v, dict)}
        assert entries
        assert all("version" in v for v in entries.values())


class TestUnverifiedIsNotClean:
    """ "Nobody looked" and "looked, and it was fine" are different answers.

    ``--audit`` always separated them (an unreachable OSV prints "do not read
    this run as a clean result"). ``--drift`` did not: a missing build toolchain
    returned the success code, so a machine without esbuild reported "All pinned
    versions match the vendored files" while the one entry that needs a build to
    verify had not been looked at.
    """

    def test_a_missing_rebuild_script_is_a_failure_not_an_unknown(self, tmp_path):
        verdict, detail = gate._check_rebuild("probe", tmp_path / "absent.sh")
        assert verdict == gate.FAIL
        assert "missing" in detail

    def test_an_unrunnable_rebuild_script_is_unverified_not_ok(self, tmp_path):
        script = tmp_path / "not_executable.sh"
        script.write_text("#!/bin/sh\nexit 0\n")  # no +x -> OSError on exec
        verdict, _detail = gate._check_rebuild("probe", script)
        assert verdict == gate.UNVERIFIED

    def test_exit_127_is_unverified_not_ok(self, tmp_path):
        script = tmp_path / "no_toolchain.sh"
        script.write_text("#!/bin/sh\nexit 127\n")
        script.chmod(0o755)
        verdict, detail = gate._check_rebuild("probe", script)
        assert verdict == gate.UNVERIFIED
        assert "toolchain" in detail

    def test_a_stale_artefact_is_a_failure(self, tmp_path):
        script = tmp_path / "stale.sh"
        script.write_text("#!/bin/sh\necho drifted >&2\nexit 1\n")
        script.chmod(0o755)
        verdict, detail = gate._check_rebuild("probe", script)
        assert verdict == gate.FAIL
        assert "drifted" in detail

    def test_a_current_artefact_passes(self, tmp_path):
        script = tmp_path / "current.sh"
        script.write_text("#!/bin/sh\nexit 0\n")
        script.chmod(0o755)
        assert gate._check_rebuild("probe", script)[0] == gate.OK

    def test_libraries_with_no_probe_are_counted_as_unverified(self):
        """They are not failures, but they are not evidence either."""
        libs = gate._load_manifest()
        _failures, unverified = gate.check_drift(libs)
        no_probe = {
            name
            for name, spec in libs.items()
            if isinstance(spec, dict)
            and not spec.get("probe")
            and not spec.get("rebuild")
        }
        assert no_probe, "no unprobed libraries — this assertion is vacuous"
        assert no_probe <= set(unverified)

    def test_the_live_tree_has_no_drift(self):
        failures, _unverified = gate.check_drift(gate._load_manifest())
        assert failures == 0
