"""Shared dependency probes and skip machinery for the real-dependency suites.

``tests/contract``, ``tests/process`` and ``tests/loading`` all need to know
whether a usable PostgreSQL (and, for contract, ``psql``/``pg_dump``) is
present.  Each carried its own near-identical ``_pg_reachable()`` and ran it at
MODULE IMPORT time, so:

* the probe existed twice and could drift — and had: one guarded ``ImportError``
  separately, the other folded it into a bare ``except Exception``;
* every collection paid a real ``psycopg.connect``, TWICE when both suites were
  named in one invocation.  Measured with ``PGHOST`` pointed at a black hole:
  ``pytest tests/contract tests/process --collect-only`` took **10.57 s**
  against 0.55 s with PostgreSQL up — two 5-second connect timeouts, spent
  before pytest's own collection timer even starts.

The probes are cached here so each runs at most once per process, and the suites
apply them through a marker plus an autouse skip fixture rather than through an
eagerly-evaluated ``skipif`` condition — so a run that collects but does not
execute pays nothing at all.

:func:`dependency_plugin` builds that marker/fixture pair, and
:func:`assert_dependencies_present` is the body of each suite's CI canary.  Both
used to be copy-pasted per suite, and the copies had already diverged: contract
and process shared a shape, while loading carried a two-thirds version whose
canary skipped on **the very condition it exists to detect** — so that suite
reported green while running nothing, which is exactly what the canary is for.
"""

from __future__ import annotations

import functools
import os
import shutil
from collections.abc import Callable

import pytest

# Bounded so an unreachable host fails the probe promptly instead of hanging
# collection for libpq's default (which has no timeout at all).
CONNECT_TIMEOUT_S = 5

#: CI sets this so a missing dependency is a FAILURE there and a skip locally.
#: ``.github/workflows/service_suites.yml`` sets it at job level, i.e. for every
#: one of its three steps — but only the suite that reads it is actually guarded.
REQUIRE_DEPS_VAR = "ODOO_CONTRACT_REQUIRE_DEPS"

#: ``{marker name: (probe, skip reason)}``
Requirements = dict[str, tuple[Callable[[], bool], str]]


@functools.cache
def pg_reachable() -> bool:
    """Whether a PostgreSQL this suite can connect to is up.  Probed once."""
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


def dependency_plugin(requirements: Requirements):
    """Return the ``(pytest_configure, autouse skip fixture)`` pair for a suite.

    A conftest binds both at module level::

        pytest_configure, _skip_without_dependencies = dependency_plugin(_REQUIREMENTS)

    pytest discovers a hook and a fixture by NAME in the conftest namespace, so
    binding them from a factory is equivalent to spelling them out — and keeps
    the three suites from drifting apart again.
    """

    def pytest_configure(config):
        for name in requirements:
            config.addinivalue_line(
                "markers", f"{name}: needs that external dependency"
            )

    @pytest.fixture(autouse=True)
    def _skip_without_dependencies(request):
        """Skip a test whose external dependency is absent — resolved lazily."""
        for name, (available, reason) in requirements.items():
            if request.node.get_closest_marker(name) and not available():
                pytest.skip(reason)

    return pytest_configure, _skip_without_dependencies


def assert_dependencies_present(requirements: Requirements) -> None:
    """Body of a suite's CI canary: fail here rather than skip the whole suite.

    A skip-guarded suite that silently skips is worse than no suite at all — it
    reports green while comparing nothing.  This turns a missing dependency into
    a failure wherever :data:`REQUIRE_DEPS_VAR` is set, and leaves it a skip on a
    developer's machine.

    The test that calls this must NOT carry any of the suite's ``requires_*``
    markers, or the autouse fixture above skips it first and the canary guards
    nothing.  A module-level ``pytestmark`` counts — which is how
    ``tests/loading``'s canary came to be skipped by the condition it detects.
    Keeping each canary in its own marker-free module makes that impossible.
    """
    if not os.environ.get(REQUIRE_DEPS_VAR):
        pytest.skip(f"set {REQUIRE_DEPS_VAR}=1 to enforce (do this in CI)")
    for available, reason in requirements.values():
        assert available(), reason
