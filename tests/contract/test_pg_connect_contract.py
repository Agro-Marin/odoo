"""Contract tests against a REAL PostgreSQL, ``psql`` and ``pg_dump``.

Companion to ``tests/service/test_contracts.py``, which pins the same class of
facts where no external process is needed.  Split because Tier 2
(``pytest odoo/orm/tests odoo/http/tests tests/service``) is documented
database-free and must stay that way; this package is its own invocation::

    python -m pytest tests/contract -v

Why the suite exists: every service-layer defect found in the audit that added
it was an assumption about a dependency, not a mistake in our own logic.  The
mocks were internally consistent and thoroughly exercised — they simply encoded
the wrong external behaviour, and nothing compared them to the real thing.

These tests are the comparison.  They are fast (a scratch database and a few
short-lived processes) and they fail LOUDLY at the assumption, rather than
letting it resurface as a security defect several modules away.
"""

import psycopg
import pytest

from .conftest import PG_DUMP, PG_REACHABLE, PSQL, requires_pg

MISSING_DB = "odoo_contract_no_such_db_xyzzy"


def test_dependencies_are_present():
    """Canary: the whole suite is skip-guarded, so CI must assert it actually RAN.

    A contract suite that silently skips is worse than none — it reports green
    while comparing nothing.  Set ``ODOO_CONTRACT_REQUIRE_DEPS=1`` in CI so a
    missing dependency is a failure there and a skip locally.
    """
    import os

    if not os.environ.get("ODOO_CONTRACT_REQUIRE_DEPS"):
        pytest.skip("set ODOO_CONTRACT_REQUIRE_DEPS=1 to enforce (do this in CI)")
    assert PG_REACHABLE, "no reachable PostgreSQL"
    assert PSQL, "psql not on PATH"
    assert PG_DUMP, "pg_dump not on PATH"


class TestPoolConnectFailureTranslation:
    """``odoo.db.pool`` translates a connect failure into a precise SQLSTATE class.

    That translation is a deliberate feature of this fork — ``_probe_connectable``
    plus the locale-independent ``_database_absent`` fallback, added so an absent
    database fails fast in any server locale instead of burning the pool's ~30s
    retry.  ``odoo.service.common`` and ``odoo.service.model`` both branch on the
    result.

    Nothing pinned it, so when the translation started producing
    ``InvalidCatalogName`` (a ``ProgrammingError``), ``exp_authenticate``'s
    ``except psycopg.OperationalError`` quietly stopped covering the "database
    does not exist" case — turning an ``auth="none"`` verb into a per-name
    database existence oracle.  A cross-subsystem contract with no test on it.
    """

    @requires_pg
    def test_absent_database_raises_invalid_catalog_name(self):
        """The exact type ``odoo.db`` hands to ``odoo.service`` for a missing DB."""
        import odoo.db

        with pytest.raises(psycopg.errors.InvalidCatalogName):
            with odoo.db.db_connect(MISSING_DB).cursor():
                pass

    @requires_pg
    def test_that_type_would_escape_an_operational_error_catch(self):
        """The regression, in one assertion.

        This is what ``exp_authenticate`` used to do.  It is written out here —
        rather than only asserting the class hierarchy — because the hierarchy
        fact is abstract while this is the actual shape of the bug: the handler
        does not fire, and the error escapes to the caller.
        """
        import odoo.db

        escaped = None
        try:
            with odoo.db.db_connect(MISSING_DB).cursor():
                pass
        except psycopg.OperationalError:  # the OLD, too-narrow catch
            escaped = False
        except Exception:
            escaped = True
        assert escaped is True, (
            "a missing database is now caught by `except psycopg.OperationalError`. "
            "If odoo.db.pool changed its connect-failure translation, revisit "
            "odoo.service.common._EXPECTED_CONNECT_FAILURES and the comments "
            "explaining why the catch is the broad psycopg.Error tree."
        )

    @requires_pg
    def test_authenticate_against_a_missing_database_returns_false(self):
        """The whole defect, end to end, with nothing mocked.

        The tests above pin the dependency's behaviour and the ones in
        ``tests/service`` pin ours against a MOCKED dependency — but each half
        can be right while the pair is wrong, which is exactly what happened:
        the service tests mocked ``Registry`` to raise ``OperationalError``, so
        they passed while the real pool raised something else entirely.

        This runs the real function against a real cluster.  It needs no
        knowledge of exception hierarchies to be correct, and it fails if either
        side of the contract moves.
        """
        from odoo.service.common import exp_authenticate

        assert exp_authenticate(MISSING_DB, "admin", "x", None) is False, (
            "authenticate against a non-existent database no longer returns "
            "False -- /jsonrpc and /xmlrpc/common are auth=none, so a "
            "distinguishable answer here is a database existence oracle"
        )

    @requires_pg
    def test_reachable_non_odoo_database_does_not_raise(self, scratch_db):
        """The other half of the contract: an existing-but-empty database
        CONNECTS.  ``exp_authenticate`` depends on this to reach its
        ``"res.users" not in registry.models`` guard — if a bare database raised
        instead, that guard would be dead code and the reason for it lost.
        """
        import odoo.db

        with odoo.db.db_connect(scratch_db).cursor() as cr:
            cr.execute("SELECT 1")
            assert cr.fetchone()[0] == 1
        odoo.db.close_db(scratch_db)
