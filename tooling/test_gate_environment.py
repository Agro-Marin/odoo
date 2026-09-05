from __future__ import annotations

import os
import shutil
import subprocess
import venv
import zipfile
from pathlib import Path

import pytest
from _gate_environment import check

HERE = Path(__file__).resolve().parent


@pytest.fixture(scope="module")
def empty_environment(tmp_path_factory):
    directory = tmp_path_factory.mktemp("gate-base")
    venv.EnvBuilder(with_pip=True).create(directory)
    return directory


@pytest.fixture
def profile(tmp_path, empty_environment):
    root = tmp_path / "checkout with spaces"
    tooling = root / "tooling"
    tooling.mkdir(parents=True)
    (root / "odoo-bin").touch()
    for name in ("gate", "_gate_environment.py"):
        shutil.copy2(HERE / name, tooling / name)
    environment = tooling / ".venv-gates"
    shutil.copytree(empty_environment, environment, symlinks=True)
    site_packages = next(environment.glob("lib/python*/site-packages"))
    for name in ("ruff", "mypy"):
        _install_metadata(site_packages, name, "1.0")
        executable = environment / "bin" / name
        executable.write_text(f"#!/bin/sh\necho '{name} 1.0'\n", encoding="utf-8")
        executable.chmod(0o755)
    (root / "requirements-dev.txt").write_text(
        "ruff==1.0\nmypy==1.0\n", encoding="utf-8"
    )
    return root, site_packages


def _install_metadata(site_packages, name, version, dependencies=()):
    info = site_packages / f"{name}-{version}.dist-info"
    info.mkdir()
    metadata = f"Metadata-Version: 2.1\nName: {name}\nVersion: {version}\n"
    metadata += "".join(f"Requires-Dist: {item}\n" for item in dependencies)
    (info / "METADATA").write_text(metadata, encoding="utf-8")


def _run(root):
    env = dict(os.environ)
    env.pop("ODOO_GATE_VENV", None)
    return subprocess.run(
        [str(root / "tooling" / "gate"), "python", "-c", "print('GATE_EXECUTED')"],
        capture_output=True,
        text=True,
        check=False,
        timeout=30,
        env=env,
    )


@pytest.mark.parametrize("installed", [None, "1.0", "2.0"])
def test_a_new_requirement_must_be_installed_at_its_pin(profile, installed):
    root, site_packages = profile
    if installed:
        _install_metadata(site_packages, "gate_probe", installed)
    with (root / "requirements-dev.txt").open("a", encoding="utf-8") as stream:
        stream.write("gate-probe==2.0\n")

    process = _run(root)

    assert process.returncode == (0 if installed == "2.0" else 2), process.stderr
    assert ("GATE_EXECUTED" in process.stdout) == (installed == "2.0")


def test_inactive_platform_requirements_do_not_need_installation(profile):
    root, _ = profile
    with (root / "requirements-dev.txt").open("a", encoding="utf-8") as stream:
        stream.write("absent-probe==1.0 ; sys_platform == 'nonexistent-platform'\n")

    process = _run(root)

    assert process.returncode == 0, process.stderr


@pytest.mark.parametrize("installed", ["1.5", "2.0"])
def test_requirement_ranges_are_checked_by_the_installer(profile, installed):
    root, site_packages = profile
    _install_metadata(site_packages, "gate_probe", installed)
    with (root / "requirements-dev.txt").open("a", encoding="utf-8") as stream:
        stream.write("gate-probe>=1,<2\n")

    process = _run(root)

    assert process.returncode == (0 if installed == "1.5" else 2), process.stderr


@pytest.mark.parametrize("influence", ["none", "environment", "config"])
def test_missing_transitive_dependencies_block_execution(
    profile, monkeypatch, influence
):
    root, site_packages = profile
    _install_metadata(site_packages, "gate_probe", "1.0", ["absent-child==1.0"])
    with (root / "requirements-dev.txt").open("a", encoding="utf-8") as stream:
        stream.write("gate-probe==1.0\n")
    if influence == "environment":
        monkeypatch.setenv("PIP_NO_DEPS", "1")
    elif influence == "config":
        config = root / "pip.conf"
        config.write_text("[global]\nno-deps = true\n", encoding="utf-8")
        monkeypatch.setenv("PIP_CONFIG_FILE", str(config))

    process = _run(root)

    assert process.returncode == 2
    assert "GATE_EXECUTED" not in process.stdout


def test_a_successful_plan_to_install_is_not_an_installed_environment(profile):
    root, site_packages = profile
    wheel = root / "gate_probe-2.0-py3-none-any.whl"
    info = "gate_probe-2.0.dist-info"
    with zipfile.ZipFile(wheel, "w") as archive:
        archive.writestr(
            f"{info}/METADATA",
            "Metadata-Version: 2.1\nName: gate-probe\nVersion: 2.0\n",
        )
        archive.writestr(
            f"{info}/WHEEL",
            "Wheel-Version: 1.0\nRoot-Is-Purelib: true\nTag: py3-none-any\n",
        )
        archive.writestr(f"{info}/RECORD", "")
    with (root / "requirements-dev.txt").open("a", encoding="utf-8") as stream:
        stream.write(f"{wheel}\n")

    process = _run(root)

    assert process.returncode == 2, process.stderr
    assert "would install" in process.stderr
    assert "GATE_EXECUTED" not in process.stdout
    assert not list(site_packages.glob("gate_probe*"))


@pytest.mark.parametrize("report", ["not json", "{}", '{"install": null}'])
def test_a_missing_or_malformed_installation_report_is_refused(monkeypatch, report):
    def run(*args, **kwargs):
        return subprocess.CompletedProcess(args[0], 0, report, "")

    monkeypatch.setattr(subprocess, "run", run)
    assert check(Path("requirements-dev.txt")) == 2
