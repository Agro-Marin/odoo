"""Shared dependency probes for the real-dependency suites.

``tests/contract`` and ``tests/process`` both need to know whether a usable
PostgreSQL (and, for contract, ``psql``/``pg_dump``) is present.  Each carried
its own near-identical ``_pg_reachable()`` and ran it at MODULE IMPORT time, so:

* the probe existed twice and could drift — and had: one guarded ``ImportError``
  separately, the other folded it into a bare ``except Exception``;
* every collection paid a real ``psycopg.connect``, TWICE when both suites were
  named in one invocation.  Measured with ``PGHOST`` pointed at a black hole:
  ``pytest tests/contract tests/process --collect-only`` took **10.57 s**
  against 0.55 s with PostgreSQL up — two 5-second connect timeouts, spent
  before pytest's own collection timer even starts.

The probe is cached here so it runs at most once per process, and the suites
apply it through a marker plus an autouse skip fixture (see either ``conftest``)
rather than through an eagerly-evaluated ``skipif`` condition — so a run that
collects but does not execute pays nothing at all.
"""

import functools
import shutil

# Bounded so an unreachable host fails the probe promptly instead of hanging
# collection for libpq's default (which has no timeout at all).
CONNECT_TIMEOUT_S = 5


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
