import configparser
import functools
import pathlib
import subprocess
import sys

import pytest

_REPO_ROOT = pathlib.Path(__file__).resolve().parents[3]


def _nameable_suites() -> list[str]:
    parser = configparser.ConfigParser()
    parser.read(_REPO_ROOT / "pytest.ini")
    suites = set(parser["pytest"]["testpaths"].split())
    assert suites, "pytest.ini declares no testpaths"

    for conftest in _REPO_ROOT.rglob("conftest.py"):
        if "stub_odoo_packages" in conftest.read_text(encoding="utf-8"):
            suites.add(conftest.parent.relative_to(_REPO_ROOT).as_posix())
    return sorted(suites)


@functools.cache
def _collect(suite: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, "-m", "pytest", suite, "--collect-only", "-q"],
        cwd=_REPO_ROOT,
        capture_output=True,
        text=True,
        timeout=300,
        check=False,
    )


@pytest.mark.parametrize("suite", _nameable_suites())
def test_the_suite_collects_when_named_on_its_own(suite: str) -> None:
    proc = _collect(suite)
    assert proc.returncode == 0, (
        f"`pytest {suite} --collect-only` exited {proc.returncode}. Something "
        f"under {suite} imports a package facade that the Tier-1 stubs shadow, "
        f"or reaches the framework at module scope. Import the leaf module "
        f"instead.\nstdout:\n{proc.stdout[-3000:]}\nstderr:\n{proc.stderr[-2000:]}"
    )


@pytest.mark.parametrize("suite", _nameable_suites())
def test_collection_reports_no_errors(suite: str) -> None:
    proc = _collect(suite)
    assert "error" not in proc.stdout.rsplit("\n", 3)[-2].lower(), (
        f"collection errors while enumerating {suite}:\n{proc.stdout[-3000:]}"
    )
