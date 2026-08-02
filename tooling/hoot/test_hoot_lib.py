"""Tests for the hoot runner's path anchoring and suite resolution.

``hoot_lib`` used to locate the checkout by counting parent directories, which
is exactly what breaks silently when a script is moved — and it was moved.
"""

import json
import os
from pathlib import Path

import hoot_lib as H
import pytest

# CI checks this repo out ALONE, so there is no workspace above it and no
# config to discover. Importing hoot_lib must still work there — it used to
# SystemExit at import, which is why this suite could not run in CI at all.
needs_workspace = pytest.mark.skipif(
    H.WORKSPACE is None, reason="repo-alone checkout: no workspace config"
)


class TestRootResolution:
    def test_odoo_root_is_the_checkout_root(self):
        assert (H.ODOO_ROOT / "odoo-bin").is_file()
        assert H.ODOO_BIN.is_file()

    def test_this_script_lives_under_the_resolved_root(self):
        assert Path(H.__file__).resolve().is_relative_to(H.ODOO_ROOT)

    def test_missing_marker_raises_instead_of_guessing(self):
        # hoot_lib now shares tooling/_repo_root rather than carrying its own
        # copy of the marker walk; the contract it must keep is unchanged.
        with pytest.raises(SystemExit) as excinfo:
            H.find_odoo_root(Path("/nonexistent/deep/path"), tool="hoot")
        assert "odoo-bin" in str(excinfo.value)

    @needs_workspace
    def test_workspace_is_the_directory_above_addons(self):
        assert H.ODOO_ROOT.parents[1] == H.WORKSPACE
        assert (H.WORKSPACE / "addons" / "odoo") == H.ODOO_ROOT

    def test_repo_alone_checkout_has_no_workspace(self):
        # The other half of the contract: `None`, not a guess one level up.
        assert (H.WORKSPACE is None) == (H.ODOO_ROOT.parent.name != "addons")

    @needs_workspace
    def test_config_resolves_to_a_real_file(self):
        assert H.CONF.is_file()

    def test_config_is_required_only_where_it_is_used(self):
        # Importing the module must never depend on a config; asking for one
        # when a server actually needs it must fail loudly.
        if H.CONF is None:
            with pytest.raises(SystemExit):
                H.require_conf()
        else:
            assert H.require_conf() == H.CONF


class TestSuiteResolution:
    def test_web_suite_resolves_test_files(self):
        assert H.suite_test_files("@web/core"), "@web/core resolved to no test files"

    def test_resolved_test_files_exist(self):
        assert all(Path(p).exists() for p in H.suite_test_files("@web/core"))

    def test_unknown_suite_resolves_to_nothing(self):
        assert not H.suite_test_files("@web/definitely_not_a_suite_xyz")

    def test_addons_for_suites_maps_prefix_to_module(self):
        assert "web" in H.addons_for_suites(["@web/core"])


class TestStateFile:
    def test_write_is_atomic(self, tmp_path, monkeypatch):
        # write_text truncates first, so a concurrent reader saw an empty file
        # ~69% of the time; read_all_states answers a torn read by SKIPPING the
        # entry, silently dropping a live server from --status and --stop.
        monkeypatch.setattr(H, "SCRIPT_DIR", tmp_path)
        state = {"pid": 1, "port": 8085, "db": "probe", "log": "/x.log", "started": 0.0}
        H.write_state(state)
        assert json.loads((tmp_path / ".hoot_state_probe.json").read_text()) == state
        assert not list(tmp_path.glob("*.tmp")), "temp file left behind"

    def test_rewrite_leaves_no_partial_file(self, tmp_path, monkeypatch):
        monkeypatch.setattr(H, "SCRIPT_DIR", tmp_path)
        for port in (8085, 8086, 8087):
            H.write_state({"pid": 1, "port": port, "db": "probe", "log": "", "started": 0.0})
            assert json.loads((tmp_path / ".hoot_state_probe.json").read_text())["port"] == port


class TestLogPruning:
    def test_keeps_only_the_newest_logs(self, tmp_path, monkeypatch):
        # 41 MB across 53 files had accumulated because nothing ever removed
        # them; --clean drops the database and leaves its logs.
        monkeypatch.setattr(H, "LOG_DIR", tmp_path)
        for i in range(30):
            log = tmp_path / f"server_db{i:02d}.log"
            log.write_text("x")
            os.utime(log, (i, i))
        H._prune_logs(keep=10)
        remaining = sorted(p.name for p in tmp_path.glob("*.log"))
        assert len(remaining) == 10
        assert remaining == [f"server_db{i:02d}.log" for i in range(20, 30)]

    def test_never_removes_port_lock_files(self, tmp_path, monkeypatch):
        # Those are flocked by live processes, not logs.
        monkeypatch.setattr(H, "LOG_DIR", tmp_path)
        (tmp_path / ".port_8085.lock").write_text("")
        for i in range(5):
            (tmp_path / f"server_db{i}.log").write_text("x")
        H._prune_logs(keep=1)
        assert (tmp_path / ".port_8085.lock").exists()

    def test_missing_log_dir_is_not_an_error(self, tmp_path, monkeypatch):
        monkeypatch.setattr(H, "LOG_DIR", tmp_path / "absent")
        H._prune_logs()


class TestImportExtraction:
    """`--affected` is only as honest as this: a missed import is a skipped
    suite reported as "the affected suites"."""

    def test_side_effect_import_followed_by_a_from_import(self, tmp_path):
        # The regex this replaced had an optional `(?:.+?\s+from\s+)?` group
        # under re.DOTALL, so at the side-effect import the `.+?` ran across
        # newlines to the next ` from ` and captured THAT specifier, swallowing
        # both statements. addons/web/static/tests/views/view_button.test.js is
        # the real instance; `@web/views/view_button` was silently unselectable.
        f = tmp_path / "x.test.js"
        f.write_text(
            'import "@web/views/form/form_utils";\n'
            'import "@web/views/view_utils";\n'
            '\n'
            'import { expect } from "@odoo/hoot";\n',
            encoding="utf-8",
        )
        assert H._imports_of(f) == {
            "@web/views/form/form_utils",
            "@web/views/view_utils",
            "@odoo/hoot",
        }

    def test_multiline_brace_import_still_resolves(self, tmp_path):
        f = tmp_path / "x.test.js"
        f.write_text(
            "import {\n    a,\n    b,\n} from \"@web/../tests/helpers\";\n", encoding="utf-8"
        )
        assert H._imports_of(f) == {"@web/../tests/helpers"}

    def test_type_only_jsdoc_import_creates_no_edge(self, tmp_path):
        # A type reference is not a reason to re-run a suite.
        f = tmp_path / "x.test.js"
        f.write_text(
            '/** @import { T } from "@web/views/gone" */\n'
            'import { a } from "@web/core/a";\n',
            encoding="utf-8",
        )
        assert H._imports_of(f) == {"@web/core/a"}

    def test_dynamic_import_is_an_edge(self, tmp_path):
        f = tmp_path / "x.test.js"
        f.write_text('const m = await import("@web/core/lazy");\n', encoding="utf-8")
        assert H._imports_of(f) == {"@web/core/lazy"}


class TestDbNameValidation:
    def test_generated_names_are_accepted(self):
        for db in ("hoot_web", "hoot_bus_mail", H.db_for_modules(("web", "mail"))):
            assert H.check_db_name(db) == db

    @pytest.mark.parametrize(
        "bad",
        ['x"; DROP DATABASE y; --', "hoot web", "hoot-web", "", "hoot';"],
    )
    def test_unsafe_names_are_refused_before_reaching_psql(self, bad):
        # `--db` is user-supplied and is spliced into DROP DATABASE and into a
        # --db-filter regex.
        with pytest.raises(SystemExit):
            H.check_db_name(bad)


class TestShardRunnerCoversCI:
    """The test ``hoot-shard``'s docstring claims exists, and did not.

    ``default_web_suites`` used to be a hand-maintained copy carrying a "KEEP
    IN SYNC" comment; it had lost ``@html_editor`` (4766 tests, 494 s) and
    ``@web/libs``, so a "full web" run covered 66% of the tests. It now derives
    the list from the CI runner's AST — but that read is failure-suppressed, so
    the new failure mode is an EMPTY list, which is the same silent under-run
    wearing different clothes.
    """

    def test_ci_runner_suites_is_not_empty(self):
        assert H.ci_runner_suites("web"), (
            "reading web/tests/test_js.py yielded no suites — hoot-shard would "
            "run nothing and call it a pass"
        )

    def test_covers_the_two_prefixes_that_were_once_lost(self):
        suites = H.ci_runner_suites("web")
        assert any(s.startswith("@html_editor") for s in suites)
        assert "@web/libs" in suites

    def test_matches_what_the_runner_declares(self):
        # Derived, not copied: parse the same file independently and compare.
        import ast

        runner = H.ODOO_ROOT / "addons" / "web" / "tests" / "test_js.py"
        assert runner.is_file(), runner
        declared = H._run_hoot_args(ast.parse(runner.read_text(encoding="utf-8")))
        assert declared == H.ci_runner_suites("web")

    def test_star_args_in_the_runner_are_expanded(self):
        # A `*SUITES` splat inside _run_hoot(...) must expand, or the plan
        # silently loses every suite the constant held.
        import ast

        tree = ast.parse(
            "SUITES = ('@web/a', '@web/b')\n"
            "class S:\n"
            "    def test_x(self):\n"
            "        self._run_hoot(*SUITES, '@web/c')\n"
        )
        assert H._run_hoot_args(tree) == {"@web/a", "@web/b", "@web/c"}


class TestShardWeights:
    def test_weights_file_lives_under_data(self):
        weights = Path(H.__file__).resolve().parent / "data" / "hoot_shard_weights.json"
        assert weights.is_file(), "hoot-shard's weights table did not survive the move"
