import contextlib
import io
import json
import sys
from pathlib import Path
from unittest import mock

import generate_service_types as gen
import pytest
from _repo_root import find_odoo_root


class TestRootResolution:
    def test_odoo_root_is_the_checkout_root(self):
        assert (gen.ODOO_ROOT / "odoo-bin").is_file()

    def test_web_src_root_resolves_without_a_workspace_prefix(self):
        assert gen.WEB_SRC_ROOT.is_dir()
        assert gen.WEB_SRC_ROOT == gen.ODOO_ROOT / "addons/web/static/src"

    def test_missing_marker_raises_instead_of_guessing(self):
        with pytest.raises(SystemExit):
            find_odoo_root(Path("/nonexistent/deep/path"), tool="probe")


class TestOutputPathsAreMachineIndependent:
    def test_rel_strips_the_checkout_root(self):
        assert gen._rel(gen.ODOO_ROOT / "addons/web/x.ts") == Path("addons/web/x.ts")

    def test_rel_never_returns_an_absolute_in_tree_path(self):
        assert not gen._rel(gen.DEFAULT_OUTPUT).is_absolute()

    def test_rel_passes_through_paths_outside_the_checkout(self):
        outside = Path("/somewhere/else/x.ts")
        assert gen._rel(outside) == outside


class TestDiscovery:
    def test_discovers_registrations(self):
        assert gen.discover(), "no service registrations found under web/static/src"

    def test_finds_a_known_core_service(self):
        keys = {r.key for r in gen.discover()}
        assert "orm" in keys

    def test_import_paths_are_web_specifiers(self):
        assert all(r.import_path.startswith("@web/") for r in gen.discover())

    def test_test_and_legacy_registrations_are_skipped(self):
        sources = [str(r.source_file) for r in gen.discover()]
        assert not [s for s in sources if "/tests/" in s or "/legacy/" in s]


class TestUntypedRegistrationCount:
    def test_count_prints_a_bare_integer(self):
        buf = io.StringIO()
        with (
            mock.patch.object(sys, "argv", ["g", "--count"]),
            contextlib.redirect_stdout(buf),
            contextlib.redirect_stderr(io.StringIO()),
        ):
            assert gen.main() == 0
        assert buf.getvalue().strip().isdigit()

    def test_the_count_is_the_registrations_that_cannot_be_typed(self):
        skipped: list[str] = []
        with contextlib.redirect_stderr(io.StringIO()):
            typed = gen.discover(skipped=skipped)
        assert typed, "no service was typed at all"
        assert skipped, "nothing was skipped, so the floor measures nothing"
        for entry in skipped:
            assert entry not in [r.key for r in typed]

    def test_the_count_matches_its_committed_floor(self):
        floor = json.loads(
            (
                gen.ODOO_ROOT
                / "tooling"
                / "ratchet"
                / "baselines"
                / "service_types_untyped.json"
            ).read_text(encoding="utf-8")
        )["count"]
        skipped: list[str] = []
        with contextlib.redirect_stderr(io.StringIO()):
            gen.discover(skipped=skipped)
        assert len(skipped) == floor, (
            "move the floor in the same change:\n"
            "    python tooling/codegen/generate_service_types.py --count \\\n"
            "        | xargs python tooling/ratchet/ratchet.py "
            "service_types_untyped --count --update --note '<what moved>'"
        )

    def test_a_scan_that_finds_nothing_is_refused(self):
        buf = io.StringIO()
        with (
            mock.patch.object(gen, "discover", lambda **_: []),
            mock.patch.object(sys, "argv", ["g", "--check"]),
            contextlib.redirect_stderr(buf),
        ):
            assert gen.main() == 2
        assert "no service registration found" in buf.getvalue()
