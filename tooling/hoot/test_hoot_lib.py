import json
import os
import shutil
import subprocess
import sys
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
