import importlib.machinery
import importlib.util
import io
import os
import subprocess
import sys
from contextlib import redirect_stdout
from itertools import chain
from pathlib import Path

import pytest

HERE = Path(__file__).resolve().parent


def _load(name: str, filename: str):
    path = HERE / filename
    loader = importlib.machinery.SourceFileLoader(name, str(path))
    spec = importlib.util.spec_from_loader(name, loader)
    module = importlib.util.module_from_spec(spec)
    loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def shard():
    return _load("hoot_shard_cli", "hoot-shard")


@pytest.fixture(scope="module")
def cli():
    return _load("hoot_cli", "hoot")


class TestScriptsAreImportable:
    @pytest.mark.parametrize("filename", ["hoot", "hoot-shard", "hoot-affected"])
    def test_each_cli_imports(self, filename):
        module = _load(f"probe_{filename.replace('-', '_')}", filename)
        assert callable(getattr(module, "main", None))

    def test_the_shared_trampoline_is_present(self):
        assert (HERE.parent / "_trampoline.sh").is_file()

    @pytest.mark.parametrize("filename", ["hoot", "hoot-shard", "hoot-affected"])
    def test_docstring_is_the_documentation_not_the_trampoline(self, filename):

        module = _load(f"doc_{filename.replace('-', '_')}", filename)
        doc = module.__doc__ or ""
        assert not doc.lstrip().startswith(":'"), (
            f"{filename}: __doc__ is the shell preamble — rebind it with an "
            f'explicit `__doc__ = """..."""` after the polyglot block'
        )
        assert "_trampoline.sh" not in doc, f"{filename}: shell leaked into __doc__"
        assert len(doc.splitlines()) > 5, f"{filename}: __doc__ lost its content"

    def test_hoot_help_renders_its_own_documentation(self):
        cli = _load("help_probe_hoot", "hoot")
        buf = io.StringIO()
        argv = sys.argv
        sys.argv = ["hoot", "--help"]
        try:
            with redirect_stdout(buf), pytest.raises(SystemExit):
                cli.main()
        finally:
            sys.argv = argv
        rendered = buf.getvalue()
        assert "warm-server HOOT test runner" in rendered
        assert "_trampoline.sh" not in rendered


class TestShardSummaryParsing:
    def _parse(self, shard, raw, rc=0):
        result = shard.ShardResult(0, "hoot_web")
        result.raw = raw
        result.rc = rc
        result.parse()
        return result

    def test_pass_line(self, shard):
        r = self._parse(shard, "PASS  @web/core  (78 passed, 3.2s)\n")
        assert (r.status, r.passed, r.failed, r.wall) == ("PASS", 78, 0, 3.2)

    def test_fail_line_with_bullets(self, shard):
        r = self._parse(
            shard,
            "FAIL  @web/core  (2 failed / 9 passed, 30.0s)\n"
            "  - @web/core/domain/one\n"
            "  - @web/core/domain/two\n",
            rc=1,
        )
        assert (r.status, r.failed, r.passed) == ("FAIL", 2, 9)
        assert r.failed_tests == ["@web/core/domain/one", "@web/core/domain/two"]

    def test_a_broken_run_with_no_summary_is_a_failure_not_silence(self, shard):
        r = self._parse(shard, "Traceback (most recent call last):\n", rc=1)
        assert r.status == "FAIL"
        assert r.failed >= 1

    def test_a_clean_run_with_no_summary_stays_unknown(self, shard):
        r = self._parse(shard, "", rc=0)
        assert r.status == "?"

    @pytest.mark.parametrize(
        "make",
        [
            lambda H: H.RunResult(ok=True, suites=["@web/core"], passed=78, wall=3.2),
            lambda H: H.RunResult(
                ok=False,
                suites=["@web/core"],
                passed=9,
                failed=2,
                wall=30.0,
                failed_tests=["@web/core/a", "@web/core/b"],
            ),
            lambda H: H.RunResult(
                ok=False, suites=["@web/core"], passed=5, wall=12.5, incomplete=True
            ),
            lambda H: H.RunResult(
                ok=False,
                suites=["@web/core"],
                passed=9,
                failed=2,
                wall=30.0,
                incomplete=True,
                failed_tests=["@web/core/a"],
            ),
        ],
        ids=["pass", "fail", "warn-truncated-clean", "fail-truncated"],
    )
    def test_round_trip_report_then_parse(self, cli, shard, make):
        import hoot_lib as H

        result = make(H)
        buffer = io.StringIO()
        with redirect_stdout(buffer):
            cli._report(result)
        parsed = self._parse(shard, buffer.getvalue(), rc=1 if result.failed else 0)
        assert parsed.status in ("PASS", "FAIL", "WARN"), buffer.getvalue()
        assert parsed.passed == result.passed
        assert parsed.failed == result.failed
        assert parsed.wall == pytest.approx(result.wall)
        assert parsed.failed_tests == result.failed_tests


class TestShardPartitioning:
    def test_heaviest_suite_lands_alone_against_the_rest(self, shard):
        weights = {"heavy": 100.0, "a": 10.0, "b": 10.0, "c": 10.0}
        shards = shard.partition(list(weights), 2, weights)
        assert ["heavy"] in shards
        assert sorted(chain.from_iterable(shards)) == sorted(weights)

    def test_every_suite_is_scheduled_exactly_once(self, shard):
        weights = {f"s{i}": float(i % 7 + 1) for i in range(40)}
        shards = shard.partition(list(weights), 5, weights)
        assert sorted(chain.from_iterable(shards)) == sorted(weights)

    def test_empty_shards_are_dropped(self, shard):
        weights = {"only": 1.0}
        assert shard.partition(["only"], 8, weights) == [["only"]]

    def test_lpt_beats_the_naive_split_it_replaced(self, shard):
        weights = {"heavy": 494.0, **{f"s{i}": 20.0 for i in range(31)}}
        shards = shard.partition(list(weights), 4, weights)
        makespan = max(sum(weights[s] for s in group) for group in shards)
        assert makespan == pytest.approx(494.0), (
            "the 494s suite must set the makespan, alone"
        )

    def test_a_measured_weight_wins_over_the_file_count_estimate(self, shard):
        assert shard.weight_of("@web/core", {"@web/core": 42.0}) == pytest.approx(42.0)

    def test_an_unknown_suite_is_estimated_not_defaulted(self, shard):
        estimate = shard.weight_of("@web/core", {})
        assert estimate > 0


class TestShardDeadline:
    def test_scales_with_the_suite_count(self, shard):
        args = type("A", (), {"timeout": 100})()
        assert shard.shard_deadline(["a"], args) < shard.shard_deadline(
            ["a", "b"], args
        )

    def test_includes_the_cold_boot_allowance(self, shard):
        args = type("A", (), {"timeout": 100})()
        assert shard.shard_deadline(["a"], args) >= 100 + shard.SHARD_BOOT_GRACE_S


class TestWeightsAreReadOnly:
    def test_load_weights_does_not_write(self, shard, tmp_path, monkeypatch):
        monkeypatch.setattr(shard, "WEIGHTS_PATH", tmp_path / "absent.json")
        assert shard.load_weights() == shard.SEED_WEIGHTS
        assert not list(tmp_path.iterdir())

    def test_a_corrupt_weights_file_falls_back_to_the_seed(
        self, shard, tmp_path, monkeypatch
    ):
        broken = tmp_path / "w.json"
        broken.write_text("{not json")
        monkeypatch.setattr(shard, "WEIGHTS_PATH", broken)
        assert shard.load_weights() == shard.SEED_WEIGHTS


class TestPresetEnvironment:
    def test_mobile_sends_the_tag_ci_sends(self, cli):
        assert cli.PRESET_ENV["mobile"]["tag"] == "-headless"
        assert cli.PRESET_ENV["desktop"]["tag"] == ""

    def test_each_preset_declares_its_viewport(self, cli):
        for preset, env in cli.PRESET_ENV.items():
            width, _, height = env["size"].partition("x")
            assert width.isdigit() and height.isdigit(), preset
        assert cli.PRESET_ENV["mobile"]["touch"] is True


class TestColourContract:
    def test_both_clis_share_one_colour_source(self, cli, shard):
        import hoot_lib as H

        assert cli.C_RED == shard.C_RED == H.C_RED

    def test_colour_is_suppressed_off_a_terminal(self, shard, monkeypatch):
        monkeypatch.setattr(sys, "stdout", io.StringIO())
        assert shard._color("PASS", shard.C_GREEN) == "PASS"


class TestThePolyglotPreambleStillExecutes:
    SCRIPTS = ("hoot", "hoot-affected", "hoot-shard")
    WITH_USAGE = ("hoot", "hoot-shard")

    def _run(self, name, *args):
        return subprocess.run(
            [str(HERE / name), *args],
            capture_output=True,
            text=True,
            timeout=120,
            check=False,
            env={**os.environ, "ODOO_VENV_PYTHON": sys.executable},
        )

    @pytest.mark.parametrize("name", SCRIPTS)
    def test_the_script_runs_and_reaches_its_python_half(self, name):
        done = self._run(name, "--help")
        assert done.returncode == 0, (
            f"{name} --help exited {done.returncode} — the sh/python polyglot "
            f"preamble is broken, so the file never reached Python.\n"
            f"stdout: {done.stdout[:400]}\nstderr: {done.stderr[:400]}"
        )
        if name in self.WITH_USAGE:
            assert "usage" in (done.stdout + done.stderr).lower()

    @pytest.mark.parametrize("name", SCRIPTS)
    def test_the_shell_preamble_is_the_single_quoted_polyglot(self, name):

        lines = (HERE / name).read_text(encoding="utf-8").splitlines()
        assert lines[0] == "#!/bin/sh"
        start = next((i for i, ln in enumerate(lines[1:12], 1) if ln == "''':'"), None)
        assert start is not None, (
            f"{name}: no \"''':'\" opener in the first 12 lines — if it was "
            f'rewritten to \'"""\' the file is already broken for /bin/sh'
        )
        assert all(ln.startswith("#") for ln in lines[1:start]), (
            f"{name}: line(s) between the shebang and the polyglot opener are "
            f"not comments, so /bin/sh executes them: {lines[1:start]!r}"
        )
        assert "'''" in lines[start:12], f"{name}: preamble is never closed"

    @pytest.mark.parametrize("name", SCRIPTS)
    def test_the_preamble_is_guarded_against_ruff_format(self, name):
        lines = (HERE / name).read_text(encoding="utf-8").splitlines()
        start = lines.index("''':'")
        end = lines.index("'''", start)
        assert "# fmt: off" in lines[:start], (
            f"{name}: the polyglot preamble is not preceded by `# fmt: off` — "
            f"ruff format will rewrite ''' to '\"\"\"' and break /bin/sh"
        )
        assert "# fmt: on" in lines[end : end + 3], (
            f"{name}: `# fmt: on` does not follow the preamble, so formatting "
            f"stays disabled for the whole file"
        )

    @pytest.mark.parametrize("name", SCRIPTS)
    def test_sh_parses_the_preamble(self, name):

        lines = (HERE / name).read_text(encoding="utf-8").splitlines()
        end = next((i for i, ln in enumerate(lines[1:], 1) if ln == "'''"), None)
        assert end is not None, (
            f"{name}: no closing ''' in the preamble — if it was rewritten to "
            f'\'"""\' the file is already broken for /bin/sh'
        )
        done = subprocess.run(
            ["sh", "-n", "-c", "\n".join(lines[1:end])],
            capture_output=True,
            text=True,
            timeout=30,
            check=False,
        )
        assert done.returncode == 0, (
            f"{name}: /bin/sh cannot parse this file — the polyglot preamble is "
            f"broken and every invocation will abort before the re-exec.\n"
            f"{done.stderr.strip()}"
        )
