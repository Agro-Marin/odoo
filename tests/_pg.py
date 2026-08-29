from __future__ import annotations

import functools
import os
import shutil
from collections.abc import Callable
from pathlib import Path

import pytest

CONNECT_TIMEOUT_S = 5

REQUIRE_DEPS_VAR = "ODOO_CONTRACT_REQUIRE_DEPS"

Requirements = dict[str, tuple[Callable[[], bool], str]]


@functools.cache
def pg_reachable() -> bool:
    try:
        import psycopg

        psycopg.connect(dbname="postgres", connect_timeout=CONNECT_TIMEOUT_S).close()
    except Exception:
        return False
    return True


@functools.cache
def psql_path() -> str | None:
    return shutil.which("psql")


@functools.cache
def pg_dump_path() -> str | None:
    return shutil.which("pg_dump")


@functools.cache
def createdb_path() -> str | None:
    return shutil.which("createdb")


@functools.cache
def dropdb_path() -> str | None:
    return shutil.which("dropdb")


@functools.cache
def repo_root() -> Path:
    for parent in Path(__file__).resolve().parents:
        if (parent / "odoo-bin").is_file():
            return parent
    raise RuntimeError("no odoo-bin marker above tests/_pg.py")


def dependency_plugin(requirements: Requirements):
    def pytest_configure(config):
        for name in requirements:
            config.addinivalue_line(
                "markers", f"{name}: needs that external dependency"
            )

    @pytest.fixture(autouse=True)
    def _skip_without_dependencies(request):
        for name, (available, reason) in requirements.items():
            if request.node.get_closest_marker(name) and not available():
                pytest.skip(reason)

    return pytest_configure, _skip_without_dependencies


def assert_dependencies_present(requirements: Requirements) -> None:
    if not os.environ.get(REQUIRE_DEPS_VAR):
        pytest.skip(f"set {REQUIRE_DEPS_VAR}=1 to enforce (do this in CI)")
    for available, reason in requirements.values():
        assert available(), reason
