import json
import os
import re
import shutil
import subprocess
import sys
from contextlib import contextmanager
from pathlib import Path

import hoot_lib as H
import pytest

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
        with pytest.raises(SystemExit) as excinfo:
            H.find_odoo_root(Path("/nonexistent/deep/path"), tool="hoot")
        assert "odoo-bin" in str(excinfo.value)

    @needs_workspace
    def test_workspace_contains_this_checkout(self):
        assert H.ODOO_ROOT.is_relative_to(H.WORKSPACE)
        if H.ODOO_ROOT.parent.name == "addons":
            assert H.ODOO_ROOT.parents[1] == H.WORKSPACE
        else:
            assert H.ODOO_ROOT.parent == H.WORKSPACE

    def test_repo_alone_checkout_has_no_workspace(self):
        from _repo_root import in_workspace

        assert (H.WORKSPACE is None) == (not in_workspace(H.ODOO_ROOT))

    @needs_workspace
    def test_config_resolves_to_a_real_file(self):
        assert H.CONF.is_file()

    def test_config_is_required_only_where_it_is_used(self):
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
        monkeypatch.setattr(H, "SCRIPT_DIR", tmp_path)
        state = {"pid": 1, "port": 8085, "db": "probe", "log": "/x.log", "started": 0.0}
        H.write_state(state)
        assert json.loads((tmp_path / ".hoot_state_probe.json").read_text()) == state
        assert not list(tmp_path.glob("*.tmp")), "temp file left behind"

    def test_rewrite_leaves_no_partial_file(self, tmp_path, monkeypatch):
        monkeypatch.setattr(H, "SCRIPT_DIR", tmp_path)
        for port in (8085, 8086, 8087):
            H.write_state(
                {"pid": 1, "port": port, "db": "probe", "log": "", "started": 0.0}
            )
            assert (
                json.loads((tmp_path / ".hoot_state_probe.json").read_text())["port"]
                == port
            )


class TestLogPruning:
    def test_keeps_only_the_newest_logs(self, tmp_path, monkeypatch):
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
        monkeypatch.setattr(H, "LOG_DIR", tmp_path)
        (tmp_path / ".port_8085.lock").write_text("")
        for i in range(5):
            (tmp_path / f"server_db{i}.log").write_text("x")
        H._prune_logs(keep=1)
        assert (tmp_path / ".port_8085.lock").exists()

    def test_missing_log_dir_is_not_an_error(self, tmp_path, monkeypatch):
        monkeypatch.setattr(H, "LOG_DIR", tmp_path / "absent")
        monkeypatch.setattr(H, "SCRIPT_DIR", tmp_path)
        H._prune_logs()

    def _live_server(self, tmp_path, monkeypatch):
        monkeypatch.setattr(H, "LOG_DIR", tmp_path)
        monkeypatch.setattr(H, "SCRIPT_DIR", tmp_path)
        log = tmp_path / "server_hoot_web.log"
        log.write_text("live")
        os.utime(log, (0, 0))
        proc = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(30)"])
        (tmp_path / ".hoot_state.json").write_text(
            json.dumps(
                {
                    "pid": proc.pid,
                    "port": 8085,
                    "db": "hoot_web",
                    "log": str(log),
                    "started": 0,
                }
            )
        )
        for i in range(25):
            other = tmp_path / f"server_other{i:02d}.log"
            other.write_text("x")
            os.utime(other, (i + 1, i + 1))
        return log, proc

    def test_a_live_servers_log_is_never_pruned(self, tmp_path, monkeypatch):
        log, proc = self._live_server(tmp_path, monkeypatch)
        try:
            H._prune_logs(keep=5)
            assert H._pid_alive(proc.pid), "the server is still running"
            assert log.exists(), "prune deleted a live warm server's log"
        finally:
            proc.terminate()
            proc.wait()

    def test_a_dead_servers_log_is_still_pruned(self, tmp_path, monkeypatch):
        log, proc = self._live_server(tmp_path, monkeypatch)
        proc.terminate()
        proc.wait()
        H._prune_logs(keep=5)
        assert not log.exists()


class TestImportExtraction:
    def test_side_effect_import_followed_by_a_from_import(self, tmp_path):
        f = tmp_path / "x.test.js"
        f.write_text(
            'import "@web/views/form/form_utils";\n'
            'import "@web/views/view_utils";\n'
            "\n"
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
            'import {\n    a,\n    b,\n} from "@web/../tests/helpers";\n',
            encoding="utf-8",
        )
        assert H._imports_of(f) == {"@web/../tests/helpers"}

    def test_type_only_jsdoc_import_creates_no_edge(self, tmp_path):
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

    def test_a_relative_import_resolves_to_its_specifier(self, tmp_path):
        src = tmp_path / "web" / "static" / "src" / "core" / "py_js"
        src.mkdir(parents=True)
        f = src / "py.js"
        f.write_text(
            'import { BUILTINS } from "./py_builtin.js";\n'
            'import { parse } from "./py_parser.js";\n'
            'import { registry } from "@web/core/registry";\n',
            encoding="utf-8",
        )
        assert H._imports_of(f) == {
            "@web/core/py_js/py_builtin",
            "@web/core/py_js/py_parser",
            "@web/core/registry",
        }

    def test_a_parent_relative_import_normalises(self, tmp_path):
        src = tmp_path / "web" / "static" / "src" / "views" / "list"
        src.mkdir(parents=True)
        f = src / "list_renderer.js"
        f.write_text('import { a } from "../view_utils.js";\n', encoding="utf-8")
        assert H._imports_of(f) == {"@web/views/view_utils"}

    def test_a_relative_import_that_escapes_the_addon_is_dropped(self, tmp_path):
        src = tmp_path / "web" / "static" / "src" / "core"
        src.mkdir(parents=True)
        f = src / "a.js"
        f.write_text(
            'import { a } from "../../lib/x.js";\nimport { b } from "./b.js";\n',
            encoding="utf-8",
        )
        assert H._imports_of(f) == {"@web/core/b"}

    def test_a_relative_import_outside_an_addon_is_dropped(self, tmp_path):
        f = tmp_path / "x.js"
        f.write_text('import { a } from "./sibling.js";\n', encoding="utf-8")
        assert H._imports_of(f) == set()

    def test_the_probe_admits_a_relative_spelling_of_a_wanted_specifier(self, tmp_path):
        src = tmp_path / "web" / "static" / "src" / "core" / "py_js"
        src.mkdir(parents=True)
        f = src / "py.js"
        f.write_text('import { B } from "./py_builtin.js";\n', encoding="utf-8")
        probe = H._specifier_probe({"@web/core/py_js/py_builtin"})
        assert H._imports_of(f, probe) == {"@web/core/py_js/py_builtin"}


class TestSpecifierProbe:
    def test_no_probe_parses_everything(self, tmp_path):
        f = tmp_path / "x.js"
        f.write_text('import "@web/core/a";\n', encoding="utf-8")
        assert H._imports_of(f, None) == {"@web/core/a"}

    def test_a_file_the_probe_misses_is_skipped(self, tmp_path):
        f = tmp_path / "x.js"
        f.write_text('import "@web/core/a";\n', encoding="utf-8")
        probe = H._specifier_probe({"@web/core/elsewhere"})
        assert H._imports_of(f, probe) == set()

    def test_a_file_the_probe_hits_is_parsed_in_full(self, tmp_path):
        f = tmp_path / "x.js"
        f.write_text('import "@web/core/a";\nimport "@web/core/b";\n', encoding="utf-8")
        probe = H._specifier_probe({"@web/core/b"})
        assert H._imports_of(f, probe) == {"@web/core/a", "@web/core/b"}

    def test_a_comment_only_mention_still_gets_parsed_and_then_dropped(self, tmp_path):
        f = tmp_path / "x.js"
        f.write_text(
            '/** @import { T } from "@web/core/a" */\nimport "@web/core/b";\n',
            encoding="utf-8",
        )
        probe = H._specifier_probe({"@web/core/a"})
        assert H._imports_of(f, probe) == {"@web/core/b"}

    def test_probe_escapes_regex_metacharacters(self, tmp_path):
        probe = H._specifier_probe({"@web/../tests/a.b"})
        assert probe.search('from "@web/../tests/a.b"')
        assert not probe.search('from "@web/xxtests/aXb"')

    def test_empty_specifier_set_yields_no_probe(self):
        assert H._specifier_probe(set()) is None


class TestRunSummary:
    def summarise(self, lines, *, ok=False, error=None):
        result = H.RunResult(ok=ok, suites=["@web/core"], error=error)
        return H.summarise(lines, result)

    def test_clean_summary_is_taken_verbatim(self):
        r = self.summarise(["Passed 78 tests (312 assertions)"], ok=True)
        assert (r.passed, r.failed, r.incomplete) == (78, 0, False)

    def test_failed_summary_carries_both_counts(self):
        r = self.summarise(["Failed 2 tests (76 passed"])
        assert (r.failed, r.passed) == (2, 76)

    def test_truncated_run_counts_distinct_names_not_lines(self):
        lines = ['Test "a" passed', 'Test "b" passed', 'Test "a" passed']
        r = self.summarise(lines)
        assert r.passed == 2
        assert r.repeated == 1
        assert r.incomplete is True

    def test_a_complete_run_reports_no_repeats(self):
        r = self.summarise(
            ['Test "a" passed', 'Test "b" passed', "Passed 2 tests (5 assertions)"],
            ok=True,
        )
        assert r.repeated == 0
        assert r.incomplete is False

    def test_failed_names_are_deduplicated_in_order(self):
        r = self.summarise(['Test "b" failed', 'Test "a" failed', 'Test "b" failed'])
        assert r.failed_tests == ["b", "a"]

    def test_truncated_and_failing_reports_both(self):
        r = self.summarise(['Test "a" passed', 'Test "x" failed'])
        assert (r.passed, r.failed, r.incomplete) == (1, 1, True)

    def test_no_output_at_all_stays_empty_and_not_incomplete(self):
        r = self.summarise([], error="ChromeBrowserException")
        assert (r.passed, r.failed, r.incomplete) == (0, 0, False)
        assert r.ok is False


class TestChangedFileDiscovery:
    def test_paths_git_would_quote_still_resolve(self, tmp_path, monkeypatch):
        root = tmp_path / "repo"
        src = root / "addons" / "web" / "static" / "src"
        src.mkdir(parents=True)

        def git(*args):
            subprocess.run(
                ["git", "-C", str(root), *args], check=True, capture_output=True
            )

        git("init", "-q", ".")
        git("config", "user.email", "t@t")
        git("config", "user.name", "t")
        names = ["café.js", "with space.js", "日本語.js", "plain.js"]
        for name in names:
            (src / name).write_text("const x = 1;\n", encoding="utf-8")
        git("add", "-A")
        git("commit", "-qm", "init")
        for name in names:
            (src / name).write_text("const y = 2;\n", encoding="utf-8")

        monkeypatch.setattr(H, "_git_toplevels", lambda: [root])
        changed = H.changed_web_js()
        assert {p.name for p in changed} == set(names)
        assert all(p.is_file() for p in changed)

    def test_explicit_paths_bypass_git_entirely(self, tmp_path):
        target = tmp_path / "a.js"
        target.write_text("", encoding="utf-8")
        assert H.changed_web_js([str(target)]) == [target.resolve()]

    def _repo_with(self, root, tracked_edit=True):
        src = root / "addons" / "web" / "static" / "src"
        tests = root / "addons" / "web" / "static" / "tests"
        src.mkdir(parents=True)
        tests.mkdir(parents=True)

        def git(*args):
            subprocess.run(
                ["git", "-C", str(root), *args], check=True, capture_output=True
            )

        git("init", "-q", ".")
        git("config", "user.email", "t@t")
        git("config", "user.name", "t")
        (src / "tracked.js").write_text("const x = 1;\n", encoding="utf-8")
        (root / ".gitignore").write_text("ignored/\n", encoding="utf-8")
        git("add", "-A")
        git("commit", "-qm", "init")
        if tracked_edit:
            (src / "tracked.js").write_text("const y = 2;\n", encoding="utf-8")
        return src, tests

    def test_a_brand_new_untracked_test_file_is_discovered(self, tmp_path, monkeypatch):

        root = tmp_path / "repo"
        _src, tests = self._repo_with(root, tracked_edit=False)
        (tests / "brand_new.test.js").write_text("", encoding="utf-8")

        monkeypatch.setattr(H, "_git_toplevels", lambda: [root])
        assert {p.name for p in H.changed_web_js()} == {"brand_new.test.js"}

    def test_tracked_and_untracked_are_both_reported_once(self, tmp_path, monkeypatch):
        root = tmp_path / "repo"
        _src, tests = self._repo_with(root)
        (tests / "new.test.js").write_text("", encoding="utf-8")

        monkeypatch.setattr(H, "_git_toplevels", lambda: [root])
        changed = H.changed_web_js()
        assert {p.name for p in changed} == {"tracked.js", "new.test.js"}
        assert len(changed) == len(set(changed)), "a path was reported twice"

    def test_gitignored_output_is_not_picked_up(self, tmp_path, monkeypatch):
        root = tmp_path / "repo"
        _src, _tests = self._repo_with(root, tracked_edit=False)
        ignored = root / "addons" / "web" / "static" / "src" / "ignored"
        ignored.mkdir()
        (ignored / "bundle.js").write_text("", encoding="utf-8")

        monkeypatch.setattr(H, "_git_toplevels", lambda: [root])
        assert H.changed_web_js() == []


class TestAddonDirCache:
    def test_repeated_calls_return_the_same_object(self):
        assert H.iter_addon_dirs() is H.iter_addon_dirs()

    def test_the_cached_result_cannot_be_mutated_by_a_caller(self):
        dirs = H.iter_addon_dirs()
        assert isinstance(dirs, tuple)
        with pytest.raises(AttributeError):
            dirs.append(Path("/nope"))  # type: ignore[attr-defined]

    def test_it_still_finds_the_web_addon(self):
        assert any(d.name == "web" for d in H.iter_addon_dirs())


class TestSpecifierMapping:
    def _p(self, rel):
        return H.ODOO_ROOT / rel

    def test_src_file_maps_to_its_specifier(self):
        assert (
            H.file_to_specifier(self._p("addons/web/static/src/core/domain.js"))
            == "@web/core/domain"
        )

    def test_test_file_maps_to_the_tests_specifier(self):
        assert (
            H.file_to_specifier(self._p("addons/web/static/tests/core/domain.test.js"))
            == "@web/../tests/core/domain.test"
        )

    def test_a_nested_addons_path_still_resolves_the_addon(self):
        assert (
            H.file_to_specifier(Path("/x/addons/odoo/addons/web/static/src/a.js"))
            == "@web/a"
        )

    def test_a_file_outside_a_static_tree_maps_to_nothing(self):
        assert H.file_to_specifier(Path("/x/addons/web/models/ir_ui_view.py")) is None

    def test_test_specifier_maps_to_the_suite_hoot_registers(self):
        assert (
            H.specifier_to_suite("@web/../tests/core/domain.test") == "@web/core/domain"
        )

    def test_a_src_specifier_is_not_a_suite(self):
        assert H.specifier_to_suite("@web/core/domain") is None

    def test_round_trip_for_every_web_test_file(self):
        files = [
            f for f in H._iter_test_files() if "/web/static/tests/" in f.as_posix()
        ]
        assert files
        for path in files:
            spec = H.file_to_specifier(path)
            assert spec, path
            assert H.specifier_to_suite(spec), path


class TestAffectedSuiteSelection:
    def _p(self, rel):
        return H.ODOO_ROOT / rel

    def test_a_tour_is_not_a_suite(self):
        suites = H.affected_suites(
            [self._p("addons/stock/static/tests/tours/stock_picking_tour.js")]
        )
        assert "@stock/tours/stock_picking_tour" not in suites

    def test_a_test_file_is_still_its_own_suite(self):
        assert "@stock/inventory_report_list" in H.affected_suites(
            [self._p("addons/stock/static/tests/inventory_report_list.test.js")]
        )

    def test_a_tour_does_not_suppress_the_test_files_beside_it(self):
        suites = H.affected_suites(
            [
                self._p("addons/stock/static/tests/tours/stock_picking_tour.js"),
                self._p("addons/stock/static/tests/inventory_report_list.test.js"),
            ]
        )
        assert "@stock/inventory_report_list" in suites
        assert not any(s.startswith("@stock/tours/") for s in suites)

    def test_every_selected_suite_is_one_hoot_can_register(self):
        tours = [
            f
            for f in H._iter_static_files("tests", "*.js")
            if "/tests/tours/" in f.as_posix() and not f.name.endswith(".test.js")
        ]
        assert tours
        registrable = {
            H.specifier_to_suite(spec)
            for spec in (H.file_to_specifier(f) for f in H._iter_test_files())
            if spec
        }
        for suite in H.affected_suites(tours, downstream=True):
            assert suite in registrable, suite


class TestModuleScope:
    def test_a_single_addon_run_is_scoped_to_it(self):
        assert H.module_scope_param(["@web/core", "@web/views"]) == "&module_scope=web"

    def test_a_cross_addon_run_stays_unscoped(self):
        assert H.module_scope_param(["@web/core", "@mail/discuss"]) == ""

    def test_an_empty_run_is_unscoped(self):
        assert H.module_scope_param([]) == ""

    def test_db_name_follows_the_modules_not_the_suites(self):
        assert H.db_for_modules(H.modules_for_suites(["@web/core"])) == "hoot_web"
        assert H.db_for_modules(H.modules_for_suites(["@mail/discuss"])) == "hoot_mail"
        assert (
            H.db_for_modules(H.modules_for_suites(["@mail/a", "@bus/b"]))
            == "hoot_bus_mail"
        )


class TestJobIdHash:
    VECTORS = {
        "@web/core": "e39ce9ba",
        "@web/core/autocomplete": "69a6561d",
        "@web/core/autocomplete/open dropdown on input": "ee565d54",
    }

    def test_published_vectors(self):
        for value, expected in self.VECTORS.items():
            assert H.generate_hash(value) == expected

    def test_astral_characters_hash_as_utf16_surrogate_pairs(self):
        evil = "@web/services/hotkey_service/hotkeys evil \U0001f479"
        assert H.generate_hash(evil) == "25490ab8"

    def test_matches_the_python_copy_in_the_ci_runner(self):
        import ast

        runner = H.ODOO_ROOT / "addons" / "web" / "tests" / "test_js.py"
        tree = ast.parse(runner.read_text(encoding="utf-8"))
        func = next(
            n
            for n in ast.walk(tree)
            if isinstance(n, ast.FunctionDef) and n.name == "_generate_hash"
        )
        func.args.args = [a for a in func.args.args if a.arg != "self"]
        namespace: dict = {}
        exec(compile(ast.Module([func], []), str(runner), "exec"), namespace)  # noqa: S102
        canonical = namespace["_generate_hash"]
        for value in [*self.VECTORS, "", "a", "café", "日本語", "evil \U0001f479"]:
            assert H.generate_hash(value) == canonical(value), value

    @pytest.mark.skipif(shutil.which("node") is None, reason="node not installed")
    def test_matches_the_real_javascript(self, tmp_path):
        source = (
            H.ODOO_ROOT / "addons" / "web" / "static" / "lib" / "hoot" / "hoot_utils.js"
        ).read_text(encoding="utf-8")
        start = source.index("export function generateHash(")
        end = source.index("\n}", start) + 2
        script = tmp_path / "hash.mjs"
        script.write_text(
            source[start:end].replace("export ", "", 1)
            + "\nconst input = JSON.parse(process.argv[2]);\n"
            + "console.log(JSON.stringify(input.map((s) => generateHash(s))));\n",
            encoding="utf-8",
        )
        values = [
            *self.VECTORS,
            "",
            "a",
            "café",
            "naïve — em dash",
            "日本語のテスト",
            "@web/services/hotkey_service/hotkeys evil \U0001f479",
            "\U0001f600\U0001f600",
            "astral \U0001d7d8 digit",
        ]
        out = subprocess.run(
            ["node", str(script), json.dumps(values)],
            capture_output=True,
            text=True,
            check=True,
        )
        expected = json.loads(out.stdout)
        assert [H.generate_hash(v) for v in values] == expected


class TestDbNameValidation:
    def test_generated_names_are_accepted(self):
        for db in ("hoot_web", "hoot_bus_mail", H.db_for_modules(("web", "mail"))):
            assert H.check_db_name(db) == db

    @pytest.mark.parametrize(
        "bad",
        ['x"; DROP DATABASE y; --', "hoot web", "hoot-web", "", "hoot';"],
    )
    def test_unsafe_names_are_refused_before_reaching_psql(self, bad):
        with pytest.raises(SystemExit):
            H.check_db_name(bad)


class TestClusterUnreachableIsNotAbsence:
    def _fake_psql(self, returncode, stdout="", stderr=""):
        def run(cmd, **kwargs):
            return subprocess.CompletedProcess(cmd, returncode, stdout, stderr)

        return run

    def test_a_failing_psql_raises_rather_than_reporting_absence(self, monkeypatch):
        monkeypatch.setattr(
            H.subprocess,
            "run",
            self._fake_psql(2, stderr="FATAL:  sorry, too many clients already"),
        )
        with pytest.raises(H.PostgresUnavailable) as exc:
            H.db_exists("hoot_web")
        assert "too many clients" in str(exc.value)

    def test_a_reachable_cluster_still_answers_yes_and_no(self, monkeypatch):
        monkeypatch.setattr(H.subprocess, "run", self._fake_psql(0, stdout="1\n"))
        assert H.db_exists("hoot_web") is True
        monkeypatch.setattr(H.subprocess, "run", self._fake_psql(0, stdout=""))
        assert H.db_exists("hoot_web") is False

    def test_the_error_names_the_cause_even_with_an_empty_stderr(self, monkeypatch):
        monkeypatch.setattr(H.subprocess, "run", self._fake_psql(1))
        with pytest.raises(H.PostgresUnavailable) as exc:
            H.db_exists("hoot_web")
        assert "exited 1" in str(exc.value)


@pytest.fixture
def isolated_lock_dir(tmp_path, monkeypatch):
    monkeypatch.setattr(H, "LOG_DIR", tmp_path / "locks")


class TestWarmServerSurvivesAnUnreachableCluster:
    def test_an_unreachable_cluster_reuses_instead_of_recycling(self, monkeypatch):
        stopped = []
        monkeypatch.setattr(H, "read_state", lambda db: {"db": db, "pid": 1})
        monkeypatch.setattr(H, "server_is_warm", lambda state: True)
        monkeypatch.setattr(
            H,
            "installed_modules",
            lambda db: (_ for _ in ()).throw(H.PostgresUnavailable("too many clients")),
        )
        monkeypatch.setattr(H, "stop_server", stopped.append)
        monkeypatch.setattr(
            H, "boot_server", lambda *a, **k: pytest.fail("must not reboot")
        )

        state, booted = H.ensure_server("hoot_web", ("web",))

        assert booted is False
        assert state["db"] == "hoot_web"
        assert stopped == []

    def test_a_reachable_cluster_still_recycles_a_server_missing_modules(
        self, monkeypatch, isolated_lock_dir
    ):
        stopped = []
        recorded = {"state": {"db": "hoot_web", "pid": 1}}

        def stop(db):
            stopped.append(db)
            recorded["state"] = None

        monkeypatch.setattr(H, "read_state", lambda db: recorded["state"])
        monkeypatch.setattr(H, "server_is_warm", lambda state: state is not None)
        monkeypatch.setattr(H, "installed_modules", lambda db: {"base"})
        monkeypatch.setattr(H, "stop_server", stop)
        monkeypatch.setattr(H, "boot_server", lambda *a, **k: {"db": "hoot_web"})

        _, booted = H.ensure_server("hoot_web", ("web",))

        assert booted is True
        assert stopped == ["hoot_web"]


class _Resp:
    def __init__(self, status_code):
        self.status_code = status_code


class TestBusyIsNotDead:
    def test_a_refused_connection_is_down(self, monkeypatch):
        import requests

        monkeypatch.setattr(
            requests,
            "get",
            lambda *a, **k: (_ for _ in ()).throw(requests.ConnectionError("refused")),
        )
        assert H._http_probe(9999) == "down"

    def test_a_read_timeout_is_busy_not_down(self, monkeypatch):
        import requests

        monkeypatch.setattr(
            requests,
            "get",
            lambda *a, **k: (_ for _ in ()).throw(requests.ReadTimeout("slow")),
        )
        assert H._http_probe(9999) == "busy"

    def test_a_connect_timeout_is_busy_despite_subclassing_connectionerror(
        self, monkeypatch
    ):
        import requests

        assert issubclass(requests.ConnectTimeout, requests.ConnectionError), (
            "the ordering this test guards is only needed while that holds"
        )
        monkeypatch.setattr(
            requests,
            "get",
            lambda *a, **k: (_ for _ in ()).throw(requests.ConnectTimeout("backlog")),
        )
        assert H._http_probe(9999) == "busy"

    def test_a_5xx_is_busy_not_down(self, monkeypatch):
        import requests

        monkeypatch.setattr(requests, "get", lambda *a, **k: _Resp(500))
        assert H._http_probe(9999) == "busy"

    def test_a_down_port_is_not_retried(self, monkeypatch):
        calls = []
        monkeypatch.setattr(
            H, "_http_probe", lambda port, *a: (calls.append(port), "down")[1]
        )
        monkeypatch.setattr(H.time, "sleep", lambda s: pytest.fail("must not wait"))

        assert H._server_responsive(9999) is False
        assert len(calls) == 1

    def test_a_busy_server_answering_late_is_still_responsive(self, monkeypatch):
        verdicts = iter(["busy", "busy", "up"])
        monkeypatch.setattr(H, "_http_probe", lambda port, *a: next(verdicts))
        monkeypatch.setattr(H.time, "sleep", lambda s: None)

        assert H._server_responsive(9999) is True


class TestReplacedServerIsNeverAbandoned:
    def _record(self, monkeypatch, tmp_path, *, pid_alive):
        monkeypatch.setattr(
            H, "read_state", lambda db: {"db": db, "pid": 4242, "port": 8085}
        )
        monkeypatch.setattr(H, "server_is_warm", lambda state: False)
        monkeypatch.setattr(H, "_pid_alive", lambda pid: pid_alive)
        monkeypatch.setattr(H, "state_file", lambda db: tmp_path / f".{db}.json")
        monkeypatch.setattr(
            H, "boot_server", lambda *a, **k: {"db": "hoot_web", "pid": 99}
        )

    def test_a_live_but_unresponsive_server_is_stopped_first(
        self, monkeypatch, tmp_path, isolated_lock_dir
    ):
        killed = []
        self._record(monkeypatch, tmp_path, pid_alive=True)
        monkeypatch.setattr(H, "_terminate_pid", killed.append)

        _, booted = H.ensure_server("hoot_web", ("web",))

        assert booted is True
        assert killed == [4242], "the replaced server was left running"

    def test_the_superseded_record_is_removed(
        self, monkeypatch, tmp_path, isolated_lock_dir
    ):
        self._record(monkeypatch, tmp_path, pid_alive=True)
        monkeypatch.setattr(H, "_terminate_pid", lambda pid: None)
        stale = tmp_path / ".hoot_web.json"
        stale.write_text("{}")

        H.ensure_server("hoot_web", ("web",))

        assert not stale.exists()

    def test_a_dead_record_terminates_nothing(
        self, monkeypatch, tmp_path, isolated_lock_dir
    ):
        killed = []
        self._record(monkeypatch, tmp_path, pid_alive=False)
        monkeypatch.setattr(H, "_terminate_pid", killed.append)

        H.ensure_server("hoot_web", ("web",))

        assert killed == []

    def test_the_reuse_path_terminates_nothing(self, monkeypatch):
        monkeypatch.setattr(
            H, "read_state", lambda db: {"db": db, "pid": 4242, "port": 8085}
        )
        monkeypatch.setattr(H, "server_is_warm", lambda state: True)
        monkeypatch.setattr(H, "installed_modules", lambda db: {"web"})
        monkeypatch.setattr(
            H, "_terminate_pid", lambda pid: pytest.fail("killed a healthy server")
        )
        monkeypatch.setattr(
            H, "boot_server", lambda *a, **k: pytest.fail("must not reboot")
        )

        _, booted = H.ensure_server("hoot_web", ("web",))

        assert booted is False


_RACE_WORKER = """
import os, sys, time
sys.path.insert(0, {hoot_dir!r})
from pathlib import Path
import hoot_lib as H

shared = Path(sys.argv[1])
H.SCRIPT_DIR = shared
H.LOG_DIR = shared / "logs"
H.STATE_FILE = shared / ".hoot_state.json"

def fake_boot(db, modules=("web",), verbose=False):
    time.sleep(1.0)                      # a real boot is ~12s
    state = {{"pid": os.getpid(), "port": 9000 + os.getpid() % 1000,
              "db": db, "log": "", "started": 0.0}}
    H.write_state(state)
    (shared / ("booted." + str(os.getpid()))).write_text("1")
    return state

H.boot_server = fake_boot
H._pid_alive = lambda pid: False         # so nothing is ever terminated
H.server_is_warm = lambda st: st is not None   # a recorded server is usable
H.installed_modules = lambda db: {{"web"}}
H.ensure_server("hoot_web", ("web",))
"""


class TestConcurrentBootDoesNotDuplicate:
    def test_four_concurrent_sessions_boot_one_server(self, tmp_path):
        worker = tmp_path / "worker.py"
        worker.write_text(_RACE_WORKER.format(hoot_dir=str(Path(H.__file__).parent)))
        shared = tmp_path / "shared"
        (shared / "logs").mkdir(parents=True)

        procs = [
            subprocess.Popen([sys.executable, str(worker), str(shared)])
            for _ in range(4)
        ]
        for p in procs:
            assert p.wait(timeout=120) == 0, "a racing session crashed"

        booted = list(shared.glob("booted.*"))
        records = list(shared.glob(".hoot_state*.json"))
        assert len(booted) == 1, (
            f"{len(booted)} servers booted for one db; "
            f"{len(booted) - len(records)} of them would be orphans"
        )
        assert len(records) == 1


class TestFilestoreIsDroppedWithItsDatabase:
    def _conf(self, tmp_path, monkeypatch, body):
        conf = tmp_path / "env.conf"
        conf.write_text(body)
        monkeypatch.setattr(H, "CONF", conf)
        return conf

    def test_data_dir_is_read_from_the_config(self, tmp_path, monkeypatch):
        self._conf(tmp_path, monkeypatch, "[options]\ndata_dir = /srv/odoo-data\n")
        assert H.data_dir() == Path("/srv/odoo-data")

    def test_an_inline_comment_is_not_part_of_the_path(self, tmp_path, monkeypatch):
        self._conf(
            tmp_path, monkeypatch, "[options]\ndata_dir = /srv/odoo-data ; scratch\n"
        )
        assert H.data_dir() == Path("/srv/odoo-data")

    def test_a_config_without_data_dir_says_so(self, tmp_path, monkeypatch):
        self._conf(tmp_path, monkeypatch, "[options]\nhttp_port = 8069\n")
        assert H.data_dir() is None

    def test_no_config_at_all_says_so(self, monkeypatch):
        monkeypatch.setattr(H, "CONF", None)
        assert H.data_dir() is None

    def test_the_filestore_is_removed(self, tmp_path, monkeypatch):
        self._conf(tmp_path, monkeypatch, f"[options]\ndata_dir = {tmp_path / 'd'}\n")
        store = tmp_path / "d" / "filestore" / "hoot_probe"
        store.mkdir(parents=True)
        (store / "ab" / "cd").mkdir(parents=True)
        (store / "ab" / "cd" / "blob").write_text("x")

        assert H.drop_filestore("hoot_probe") is True
        assert not store.exists()

    def test_a_neighbour_database_is_untouched(self, tmp_path, monkeypatch):
        self._conf(tmp_path, monkeypatch, f"[options]\ndata_dir = {tmp_path / 'd'}\n")
        keep = tmp_path / "d" / "filestore" / "hoot_other"
        keep.mkdir(parents=True)
        (tmp_path / "d" / "filestore" / "hoot_probe").mkdir()

        H.drop_filestore("hoot_probe")
        assert keep.is_dir(), "dropped a database's filestore took a neighbour with it"

    def test_nothing_to_remove_is_not_an_error(self, tmp_path, monkeypatch):
        self._conf(tmp_path, monkeypatch, f"[options]\ndata_dir = {tmp_path / 'd'}\n")
        (tmp_path / "d" / "filestore").mkdir(parents=True)
        assert H.drop_filestore("hoot_absent") is False

    def test_no_data_dir_removes_nothing(self, tmp_path, monkeypatch):
        self._conf(tmp_path, monkeypatch, "[options]\nhttp_port = 8069\n")
        assert H.drop_filestore("hoot_probe") is False

    @pytest.mark.parametrize("escape", ["../../etc", "..", "a/../../b", "/etc"])
    def test_a_name_that_escapes_the_filestore_is_refused(
        self, tmp_path, monkeypatch, escape
    ):
        self._conf(tmp_path, monkeypatch, f"[options]\ndata_dir = {tmp_path / 'd'}\n")
        (tmp_path / "d" / "filestore").mkdir(parents=True)
        with pytest.raises(SystemExit):
            H.drop_filestore(escape)

    def test_containment_refuses_even_if_the_name_check_is_bypassed(
        self, tmp_path, monkeypatch
    ):
        self._conf(tmp_path, monkeypatch, f"[options]\ndata_dir = {tmp_path / 'd'}\n")
        (tmp_path / "d" / "filestore").mkdir(parents=True)
        outsider = tmp_path / "d" / "not_the_filestore"
        outsider.mkdir()

        monkeypatch.setattr(H, "check_db_name", lambda db: db)

        assert H.drop_filestore("../not_the_filestore") is False
        assert outsider.is_dir(), "reached a directory outside the filestore"

    def test_a_failed_drop_leaves_the_filestore_alone(self, tmp_path, monkeypatch):
        self._conf(tmp_path, monkeypatch, f"[options]\ndata_dir = {tmp_path / 'd'}\n")
        store = tmp_path / "d" / "filestore" / "hoot_probe"
        store.mkdir(parents=True)

        class Failed:
            returncode = 1

        monkeypatch.setattr(H.subprocess, "run", lambda *a, **k: Failed())
        H.drop_db("hoot_probe")
        assert store.is_dir(), "filestore removed although DROP DATABASE failed"


class TestUntrackedServerDiscovery:
    def test_the_pattern_matches_the_flag_boot_actually_writes(self):
        assert H._DB_FILTER_RE.match("--db-filter=^hoot_web$").group(1) == "hoot_web"

    def test_a_partial_db_filter_is_not_matched(self):
        assert H._DB_FILTER_RE.match("--db-filter=^hoot_") is None

    def test_a_recorded_server_is_not_untracked(self, monkeypatch):
        monkeypatch.setattr(H, "find_server_processes", lambda: {7: "hoot_web"})
        monkeypatch.setattr(
            H, "read_all_states", lambda: [{"pid": 7, "db": "hoot_web"}]
        )

        assert H.find_untracked_servers() == {}

    def test_an_unrecorded_server_is_reported(self, monkeypatch):
        monkeypatch.setattr(
            H, "find_server_processes", lambda: {7: "hoot_web", 9: "hoot_mail"}
        )
        monkeypatch.setattr(
            H, "read_all_states", lambda: [{"pid": 7, "db": "hoot_web"}]
        )
        monkeypatch.setattr(H, "_process_age", lambda pid: H.ORPHAN_GRACE + 1)

        assert H.find_untracked_servers() == {9: "hoot_mail"}

    def test_a_booting_server_is_not_yet_an_orphan(self, monkeypatch):
        monkeypatch.setattr(H, "find_server_processes", lambda: {9: "hoot_mail"})
        monkeypatch.setattr(H, "read_all_states", list)
        monkeypatch.setattr(H, "_process_age", lambda pid: 5.0)

        assert H.find_untracked_servers() == {}

    def test_an_old_unrecorded_server_is_an_orphan(self, monkeypatch):
        monkeypatch.setattr(H, "find_server_processes", lambda: {9: "hoot_mail"})
        monkeypatch.setattr(H, "read_all_states", list)
        monkeypatch.setattr(H, "_process_age", lambda pid: H.ORPHAN_GRACE + 1)

        assert H.find_untracked_servers() == {9: "hoot_mail"}

    def test_the_grace_outlasts_the_boot_deadline(self):
        assert H.ORPHAN_GRACE > 120, "boot may take the full 120s in _boot_server_on"

    def test_an_unreadable_process_is_not_reaped(self, monkeypatch):
        monkeypatch.setattr(H, "find_server_processes", lambda: {9: "hoot_mail"})
        monkeypatch.setattr(H, "read_all_states", list)
        assert not H._process_age(2**30)
        monkeypatch.setattr(H, "_process_age", lambda pid: 0.0)
        assert H.find_untracked_servers() == {}

    def test_a_real_process_reports_a_plausible_age(self):
        proc = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(20)"])
        try:
            assert 0.0 <= H._process_age(proc.pid) < 10.0
        finally:
            proc.kill()
            proc.wait()

    def test_reaping_terminates_only_the_orphan(self, monkeypatch):
        killed = []
        monkeypatch.setattr(H, "find_untracked_servers", lambda: {9: "hoot_mail"})
        monkeypatch.setattr(H, "_terminate_pid", killed.append)
        monkeypatch.setattr(H, "drop_db", lambda db: pytest.fail("no --clean asked"))

        msg = H.stop_untracked_servers()

        assert killed == [9]
        assert "pid=9" in msg and "hoot_mail" in msg

    def test_nothing_to_reap_says_nothing(self, monkeypatch):
        monkeypatch.setattr(H, "find_untracked_servers", dict)
        assert H.stop_untracked_servers() == ""

    def test_this_checkouts_own_server_is_discoverable(self):
        found = H.find_server_processes()
        assert isinstance(found, dict)
        for pid, db in found.items():
            argv = (
                Path(f"/proc/{pid}/cmdline")
                .read_bytes()
                .decode("utf8", "replace")
                .split("\0")
            )
            assert str(H.ODOO_BIN) in argv
            assert f"--db-filter=^{db}$" in argv


class TestShardRunnerCoversCI:
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
        import ast

        runner = H.ODOO_ROOT / "addons" / "web" / "tests" / "test_js.py"
        assert runner.is_file(), runner
        declared = H._run_hoot_args(ast.parse(runner.read_text(encoding="utf-8")))
        assert declared == H.ci_runner_suites("web")

    def test_star_args_in_the_runner_are_expanded(self):
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


@contextmanager
def _env(**overrides):
    previous = {k: os.environ.get(k) for k in overrides}
    try:
        for key, value in overrides.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value
        yield
    finally:
        for key, value in previous.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value


def test_port_range_default_is_wider_than_one_workspace() -> None:
    with _env(ODOO_HOOT_PORTS=None):
        assert H._port_range() == range(8085, 8145)


def test_port_range_accepts_first_last_and_first_count() -> None:
    with _env(ODOO_HOOT_PORTS="9000-9002"):
        assert H._port_range() == range(9000, 9003)
    with _env(ODOO_HOOT_PORTS="9000+3"):
        assert H._port_range() == range(9000, 9003)
    with _env(ODOO_HOOT_PORTS="9100"):
        assert H._port_range() == range(9100, 9101)
    with _env(ODOO_HOOT_PORTS="  9000-9001  "):
        assert H._port_range() == range(9000, 9002)


def test_port_range_rejects_what_it_cannot_read() -> None:
    with _env(ODOO_HOOT_PORTS=""):
        assert H._port_range() == range(8085, 8145)
    for spec in ("nonsense", "9000-8999", "0-10", "9000-99999", "9000+0"):
        with (
            _env(ODOO_HOOT_PORTS=spec),
            pytest.raises(SystemExit, match="ODOO_HOOT_PORTS"),
        ):
            H._port_range()


def test_the_mobile_tag_pattern_matches_the_suites_own() -> None:
    upstream = (H.ODOO_ROOT / "addons" / "web" / "tests" / "test_js.py").read_text(
        encoding="utf-8"
    )
    match = re.search(r"^RE_MOBILE_TAG = re\.compile\((.*)\)$", upstream, re.MULTILINE)
    assert match, "MobileWebSuite no longer defines RE_MOBILE_TAG on one line"
    assert eval(match.group(1)) == H.RE_MOBILE_TAG.pattern, (  # noqa: S307
        "hoot_lib.RE_MOBILE_TAG has drifted from web/tests/test_js.py's"
    )


def test_mobile_tagged_files_finds_the_files_that_own_a_mobile_test() -> None:
    ui = H.mobile_tagged_files(["@web/ui"])
    names = {p.name for p in ui}
    assert "bottom_sheet.test.js" in names, names
    assert "dialog_service.test.js" in names, names
    assert "viewport.test.js" not in names, names
    assert H.mobile_tagged_files([]) == []


class TestWatcherWarning:
    WARNING = (
        "2026-01-01 00:00:00,000 1 WARNING uid:- ? odoo.service.server: "
        "Could not start the file watcher — the server runs without it, so "
        "source edits are NOT picked up."
    )

    def test_fires_on_a_log_that_carries_the_warning(self, tmp_path, caplog):
        log = tmp_path / "server_hoot_web.log"
        log.write_text(f"boot line\n{self.WARNING}\nmore\n", encoding="utf8")

        assert H.warn_if_no_watcher(log) is True
        assert "NO file watcher" in caplog.text
        assert "max_user_watches" in caplog.text

    def test_silent_on_a_healthy_log(self, tmp_path, caplog):
        log = tmp_path / "server_hoot_web.log"
        log.write_text("boot line\nHTTP service (werkzeug) running\n", encoding="utf8")

        assert H.warn_if_no_watcher(log) is False
        assert caplog.text == ""

    def test_silent_when_the_log_is_gone(self, tmp_path):
        assert H.warn_if_no_watcher(tmp_path / "absent.log") is False

    def test_the_reuse_path_checks_too(self):
        source = (Path(H.__file__)).read_text(encoding="utf8")
        reuse = source[source.index("def ensure_server") :]
        assert reuse.count("warn_if_no_watcher") >= 2, (
            "both the plain reuse branch and the cannot-re-verify branch must "
            "check, not just one"
        )
