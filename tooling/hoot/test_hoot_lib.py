"""Tests for the hoot runner's path anchoring and suite resolution.

``hoot_lib`` used to locate the checkout by counting parent directories, which
is exactly what breaks silently when a script is moved — and it was moved.
"""

import json
import os
import shutil
import subprocess
import sys
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
    def test_workspace_contains_this_checkout(self):
        # Two layouts: the checkout sits at <ws>/addons/odoo historically and at
        # <ws>/odoo since the workspace was flattened. Asserting `parents[1]`
        # unconditionally pinned the first one, and the flattening then made
        # every tool resolve WORKSPACE to None and behave as a repo-alone CI
        # checkout -- hoot refused to start, "no odoo config found", in a
        # workspace that had one.
        assert H.ODOO_ROOT.is_relative_to(H.WORKSPACE)
        if H.ODOO_ROOT.parent.name == "addons":
            assert H.ODOO_ROOT.parents[1] == H.WORKSPACE
        else:
            assert H.ODOO_ROOT.parent == H.WORKSPACE

    def test_repo_alone_checkout_has_no_workspace(self):
        # The other half of the contract: `None`, not a guess one level up.
        # A workspace is recognised by what it supplies (a venv and/or a .conf),
        # which is what the tools actually climb to it for.
        from _repo_root import in_workspace

        assert (H.WORKSPACE is None) == (not in_workspace(H.ODOO_ROOT))

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
        monkeypatch.setattr(H, "SCRIPT_DIR", tmp_path)
        H._prune_logs()

    def _live_server(self, tmp_path, monkeypatch):
        """A warm server that booted long ago and has been idle since."""
        monkeypatch.setattr(H, "LOG_DIR", tmp_path)
        monkeypatch.setattr(H, "SCRIPT_DIR", tmp_path)
        log = tmp_path / "server_hoot_web.log"
        log.write_text("live")
        os.utime(log, (0, 0))  # oldest file in the directory
        proc = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(30)"])
        (tmp_path / ".hoot_state.json").write_text(
            json.dumps({"pid": proc.pid, "port": 8085, "db": "hoot_web",
                        "log": str(log), "started": 0})
        )
        for i in range(25):
            other = tmp_path / f"server_other{i:02d}.log"
            other.write_text("x")
            os.utime(other, (i + 1, i + 1))
        return log, proc

    def test_a_live_servers_log_is_never_pruned(self, tmp_path, monkeypatch):
        # mtime order does not protect it: an idle warm server is the normal
        # state between runs, so its log is the OLDEST file, and a
        # `hoot-shard -j 8` run writes sixteen newer ones. Pruning it unlinked
        # a file the server still held open — space not reclaimed, and
        # --status pointing at a path that no longer existed.
        log, proc = self._live_server(tmp_path, monkeypatch)
        try:
            H._prune_logs(keep=5)
            assert H._pid_alive(proc.pid), "the server is still running"
            assert log.exists(), "prune deleted a live warm server's log"
        finally:
            proc.terminate()
            proc.wait()

    def test_a_dead_servers_log_is_still_pruned(self, tmp_path, monkeypatch):
        # The exemption is for LIVE servers only, or the directory would grow
        # without bound again as soon as a stale state file was left behind.
        log, proc = self._live_server(tmp_path, monkeypatch)
        proc.terminate()
        proc.wait()
        H._prune_logs(keep=5)
        assert not log.exists()


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


class TestSpecifierProbe:
    """The prefilter that makes `--affected` a 0.4 s scan instead of a 6.3 s one.

    It is sound only because a specifier `collect_imports` returns is always a
    literal substring of the source. If that ever stops holding, `--affected`
    starts silently skipping suites — the failure it is least able to report.
    """

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
        # The probe decides whether to parse, never WHAT the parse returns:
        # one hit must still yield every specifier in the file, or the one-hop
        # walk through src/ loses edges.
        f = tmp_path / "x.js"
        f.write_text('import "@web/core/a";\nimport "@web/core/b";\n', encoding="utf-8")
        probe = H._specifier_probe({"@web/core/b"})
        assert H._imports_of(f, probe) == {"@web/core/a", "@web/core/b"}

    def test_a_comment_only_mention_still_gets_parsed_and_then_dropped(self, tmp_path):
        # The probe is a text prefilter, so a JSDoc mention passes it. The
        # parse behind it is what rejects the edge — the prefilter must never
        # be the thing deciding, only the thing skipping.
        f = tmp_path / "x.js"
        f.write_text(
            '/** @import { T } from "@web/core/a" */\nimport "@web/core/b";\n',
            encoding="utf-8",
        )
        probe = H._specifier_probe({"@web/core/a"})
        assert H._imports_of(f, probe) == {"@web/core/b"}

    def test_probe_escapes_regex_metacharacters(self, tmp_path):
        # Specifiers carry `.` and `../`; an unescaped alternation would match
        # files that merely look similar, costing correctness in the cheap
        # direction (extra parses) but proving the escaping is deliberate.
        probe = H._specifier_probe({"@web/../tests/a.b"})
        assert probe.search('from "@web/../tests/a.b"')
        assert not probe.search('from "@web/xxtests/aXb"')

    def test_empty_specifier_set_yields_no_probe(self):
        assert H._specifier_probe(set()) is None


class TestRunSummary:
    """What a run MEANS: the counts printed and the flag that becomes an exit code."""

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
        # HOOT re-emits a suite's tests when a coarse id selects overlapping
        # suites, so the raw line count is not a test count: one truncated
        # @web/core run grew from 30838 to 58569 "passed" lines purely by
        # raising the timeout, for a suite declaring ~2400 tests.
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
        r = self.summarise(
            ['Test "b" failed', 'Test "a" failed', 'Test "b" failed']
        )
        assert r.failed_tests == ["b", "a"]

    def test_truncated_and_failing_reports_both(self):
        # The counts are a prefix of the suite; the CLI must be able to say so
        # rather than present them as the whole result.
        r = self.summarise(['Test "a" passed', 'Test "x" failed'])
        assert (r.passed, r.failed, r.incomplete) == (1, 1, True)

    def test_no_output_at_all_stays_empty_and_not_incomplete(self):
        # A run that produced nothing is a runner failure, reported through
        # `error`/`ok`, not a truncated run with zero tests.
        r = self.summarise([], error="ChromeBrowserException")
        assert (r.passed, r.failed, r.incomplete) == (0, 0, False)
        assert r.ok is False


class TestChangedFileDiscovery:
    def test_paths_git_would_quote_still_resolve(self, tmp_path, monkeypatch):
        # git QUOTES any path outside plain ASCII by default (`core.quotePath`),
        # so an edited src/café.js came back as
        # `"addons/web/static/src/caf\303\251.js"` — a name matching nothing on
        # disk. It was dropped and its suite left unselected, while --affected
        # reported that it had selected the affected suites.
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


class TestAddonDirCache:
    """The scan is cached for the process; the result is therefore shared."""

    def test_repeated_calls_return_the_same_object(self):
        # 68 identical walks of ~1550 directories cost 0.27s of hoot-shard's
        # 0.37s plan build.
        assert H.iter_addon_dirs() is H.iter_addon_dirs()

    def test_the_cached_result_cannot_be_mutated_by_a_caller(self):
        # A shared cached LIST would let any caller's `.append`/`.sort` corrupt
        # every later suite resolution in the process, with no way to notice.
        dirs = H.iter_addon_dirs()
        assert isinstance(dirs, tuple)
        with pytest.raises(AttributeError):
            dirs.append(Path("/nope"))  # type: ignore[attr-defined]

    def test_it_still_finds_the_web_addon(self):
        assert any(d.name == "web" for d in H.iter_addon_dirs())


class TestSpecifierMapping:
    """`--affected` maps files -> specifiers -> suite names. Every hop can lose one."""

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
        # Keyed off the `static` segment, so `addons/odoo/addons/web` does not
        # resolve the addon to `odoo`.
        assert (
            H.file_to_specifier(Path("/x/addons/odoo/addons/web/static/src/a.js"))
            == "@web/a"
        )

    def test_a_file_outside_a_static_tree_maps_to_nothing(self):
        assert H.file_to_specifier(Path("/x/addons/web/models/ir_ui_view.py")) is None

    def test_test_specifier_maps_to_the_suite_hoot_registers(self):
        # Mirrors start.hoot.js's _suiteNameFromSpecifier.
        assert H.specifier_to_suite("@web/../tests/core/domain.test") == "@web/core/domain"

    def test_a_src_specifier_is_not_a_suite(self):
        assert H.specifier_to_suite("@web/core/domain") is None

    def test_round_trip_for_every_web_test_file(self):
        # Whole-corpus: any test file whose specifier does not map back to a
        # suite is a suite `--affected` can never select.
        files = [
            f
            for f in H._iter_test_files()
            if "/web/static/tests/" in f.as_posix()
        ]
        assert files
        for path in files:
            spec = H.file_to_specifier(path)
            assert spec, path
            assert H.specifier_to_suite(spec), path


class TestModuleScope:
    """Wrong scope = a different bundle = tests that pass in CI and fail here."""

    def test_a_single_addon_run_is_scoped_to_it(self):
        assert H.module_scope_param(["@web/core", "@web/views"]) == "&module_scope=web"

    def test_a_cross_addon_run_stays_unscoped(self):
        # No single closure exists, and dropping one side's `src` would be
        # worse than running unscoped.
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
    """The id hash exists in FOUR places and nothing pinned them together.

    ``hoot_lib.generate_hash``, ``web/tests/test_js.py::_generate_hash``,
    ``start.hoot.js::_hashJobId`` and ``hoot/hoot_utils.js::generateHash`` all
    implement it, and the browser RECOMPUTES the id and keeps only the jobs
    that match. So a disagreement is not a wrong selection, it is an EMPTY
    one — reported as "matched no tests: failing closed", which reads like a
    bad suite name rather than a hash bug.
    """

    #: Published in `test_js.py::test_generate_hoot_hash`.
    VECTORS = {
        "@web/core": "e39ce9ba",
        "@web/core/autocomplete": "69a6561d",
        "@web/core/autocomplete/open dropdown on input": "ee565d54",
    }

    def test_published_vectors(self):
        for value, expected in self.VECTORS.items():
            assert H.generate_hash(value) == expected

    def test_astral_characters_hash_as_utf16_surrogate_pairs(self):
        # `charCodeAt` walks UTF-16 code units; `ord()` returns one code point
        # above 0xFFFF. Two real suites carry an astral character, so both were
        # unselectable by id until the Python side iterated units too.
        evil = "@web/services/hotkey_service/hotkeys evil \U0001f479"
        assert H.generate_hash(evil) == "25490ab8"

    def test_matches_the_python_copy_in_the_ci_runner(self):
        # Extracted from source rather than imported: `test_js.py` needs Odoo.
        # If anyone edits the canonical copy, this fails.
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
        # The only copy that actually decides anything: the browser's.
        source = (
            H.ODOO_ROOT / "addons" / "web" / "static" / "lib" / "hoot" / "hoot_utils.js"
        ).read_text(encoding="utf-8")
        start = source.index("export function generateHash(")
        end = source.index("\n}", start) + 2
        script = tmp_path / "hash.mjs"
        script.write_text(
            source[start:end].replace("export ", "", 1)
            + "\nconst input = JSON.parse(process.argv[2]);\n"
            # NOT map(generateHash): it is variadic, and map passes (el, i, arr).
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
