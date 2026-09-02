from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
GATE = ROOT / "tooling" / "gate"


def _run(*args, env=None):
    return subprocess.run(
        [str(GATE), *args], capture_output=True, text=True, check=False, env=env
    )


def test_the_pins_are_read_from_requirements_dev():
    proc = _run("--pins")
    assert proc.returncode == 0, proc.stderr
    pins = dict(line.split("==") for line in proc.stdout.split())
    text = (ROOT / "requirements-dev.txt").read_text(encoding="utf-8")
    for tool, version in pins.items():
        assert f"{tool}=={version}" in text, (tool, version)


def test_the_interpreter_is_under_tooling_by_default():
    proc = _run("--python")
    assert proc.returncode == 0, proc.stderr
    assert proc.stdout.strip() == str(
        ROOT / "tooling" / ".venv-gates" / "bin" / "python"
    )


def test_a_drifted_tool_is_refused(tmp_path):
    fake = tmp_path / "venv" / "bin"
    fake.mkdir(parents=True)
    (fake / "python").write_text("#!/bin/sh\nexit 0\n")
    (fake / "ruff").write_text('#!/bin/sh\necho "ruff 0.0.1"\n')
    (fake / "mypy").write_text('#!/bin/sh\necho "mypy 0.0.1"\n')
    for f in fake.iterdir():
        f.chmod(0o755)
    import os

    env = {**os.environ, "ODOO_GATE_VENV": str(tmp_path / "venv")}
    proc = _run("ruff", "--version", env=env)
    assert proc.returncode == 2
    assert "pins" in proc.stderr and "0.0.1" in proc.stderr


@pytest.mark.skipif(
    not (ROOT / "tooling" / ".venv-gates" / "bin" / "ruff").exists(),
    reason="the gates virtualenv has not been built here",
)
def test_a_built_venv_runs_the_pinned_ruff():
    proc = _run("ruff", "--version")
    assert proc.returncode == 0, proc.stderr
    pins = dict(l.split("==") for l in _run("--pins").stdout.split())
    assert pins["ruff"] in proc.stdout
