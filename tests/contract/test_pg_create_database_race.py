"""What PostgreSQL *actually* raises when two callers create the same database.

``_create_empty_database`` deliberately carries no pre-flight ``SELECT`` — the
``CREATE DATABASE`` itself is the existence check — and translates the
duplicate-name error into the canonical ``DatabaseExists``.  Which error that is
turns out to depend on whether the duplicate is sequential or concurrent, and
the two classify under different psycopg exceptions:

* sequential duplicate  -> ``42P04`` ``DuplicateDatabase``
* concurrent duplicate  -> ``23505`` ``UniqueViolation`` on the unique index
  over ``pg_database.datname``

``UniqueViolation`` is NOT a subclass of ``DuplicateDatabase``, so a catch
written against ``42P04`` alone misses precisely the race the pre-flight-free
design exists to handle.  Every mock-based test of that path passes anyway,
because the mock is told to raise ``DuplicateDatabase`` — it encodes the same
wrong belief as the code.  That is the whole reason this suite exists (see the
package docstring in ``test_pg_connect_contract.py``).

Requires a reachable PostgreSQL; skips otherwise, and the suite-wide
``test_dependencies_are_present`` canary is what stops that skip from silently
becoming "green" in CI.
"""

import subprocess
import threading
import uuid
from concurrent.futures import ThreadPoolExecutor

import psycopg
import pytest

from .conftest import requires_pg

RACERS = 4


def _drop(name: str) -> None:
    subprocess.run(
        ["dropdb", "--if-exists", "--force", name], check=False, capture_output=True
    )


@pytest.fixture
def race_name():
    """A database name unique to this test, dropped however the test ends."""
    name = f"odoo_race_{uuid.uuid4().hex[:12]}"
    try:
        yield name
    finally:
        _drop(name)


def _race(name: str) -> list[str | psycopg.Error]:
    """Have ``RACERS`` connections issue the same CREATE DATABASE at once.

    Returns one entry per racer: the string ``"created"`` for the winner, or the
    ``psycopg.Error`` each loser received.  A ``Barrier`` releases them together
    so the overlap is real rather than hoped for.
    """
    barrier = threading.Barrier(RACERS)

    def attempt(_):
        with psycopg.connect(dbname="postgres", autocommit=True) as conn:
            barrier.wait(timeout=30)
            try:
                conn.execute(f'CREATE DATABASE "{name}" TEMPLATE template0')
                return "created"
            except psycopg.Error as exc:
                return exc

    with ThreadPoolExecutor(max_workers=RACERS) as pool:
        return list(pool.map(attempt, range(RACERS)))


@requires_pg
class TestConcurrentCreateDatabaseSqlstate:
    """The concurrent duplicate does not use the sequential duplicate's SQLSTATE."""

    def test_exactly_one_racer_wins(self, race_name):
        """Premise of every other test here: the race really did overlap."""
        outcomes = _race(race_name)
        assert outcomes.count("created") == 1, outcomes

    def test_losers_get_unique_violation_not_duplicate_database(self, race_name):
        """The measurement the ``except`` clause is written against."""
        losers = [o for o in _race(race_name) if o != "created"]
        assert losers, "no racer lost — the barrier failed to overlap them"
        assert {type(e) for e in losers} == {psycopg.errors.UniqueViolation}, [
            (type(e).__name__, e.sqlstate) for e in losers
        ]
        assert {e.sqlstate for e in losers} == {"23505"}

    def test_unique_violation_is_not_a_duplicate_database(self):
        """Why catching ``42P04`` alone is not enough — the reason is a type
        relationship psycopg does not provide, not a stylistic preference."""
        assert not issubclass(
            psycopg.errors.UniqueViolation, psycopg.errors.DuplicateDatabase
        )
        assert psycopg.errors.DuplicateDatabase.sqlstate == "42P04"
        assert psycopg.errors.UniqueViolation.sqlstate == "23505"

    def test_sequential_duplicate_still_uses_42p04(self, race_name):
        """The other spelling must keep working: an ordinary (unraced) duplicate
        is ``DuplicateDatabase``, which is what the sequential callers see."""
        subprocess.run(
            ["createdb", "-T", "template0", race_name], check=True, capture_output=True
        )
        with psycopg.connect(dbname="postgres", autocommit=True) as conn:
            with pytest.raises(psycopg.errors.DuplicateDatabase) as excinfo:
                conn.execute(f'CREATE DATABASE "{race_name}" TEMPLATE template0')
        assert excinfo.value.sqlstate == "42P04"


@requires_pg
class TestCreateEmptyDatabaseAnswersUniformly:
    """The service verb must answer ``DatabaseExists`` for BOTH spellings.

    This is the defect stated in the service layer's own vocabulary: without
    ``UniqueViolation`` in the catch, a racing caller of ``exp_create_database``
    receives a raw ``psycopg.errors.UniqueViolation`` — an RPC Fault — where a
    sequential caller receives ``DatabaseExists``.
    """

    def test_every_losing_racer_gets_database_exists(self, race_name):
        from odoo.service.db import DatabaseExists, _create_empty_database

        barrier = threading.Barrier(RACERS)

        def attempt(_):
            barrier.wait(timeout=30)
            try:
                _create_empty_database(
                    race_name, template="template0", setup_if_exists=False
                )
                return "created"
            except DatabaseExists:
                return "DatabaseExists"
            except BaseException as exc:
                return f"{type(exc).__module__}.{type(exc).__name__}"

        with ThreadPoolExecutor(max_workers=RACERS) as pool:
            outcomes = list(pool.map(attempt, range(RACERS)))

        assert outcomes.count("created") == 1, outcomes
        losers = [o for o in outcomes if o != "created"]
        assert set(losers) == {"DatabaseExists"}, (
            f"a racing create leaked a raw driver error instead of the canonical "
            f"DatabaseExists: {sorted(set(losers))}"
        )
