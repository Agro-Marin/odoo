from unittest import mock

import odoo
from odoo.service import db as db_service
from odoo.tests import BaseCase


class TestExpDropAllowlist(BaseCase):
    """``exp_drop`` must refuse to drop a database outside ``list_dbs(True)``
    — the RPC entry point is reachable with only the master password, so
    without this gate a caller could ``DROP DATABASE`` any DB owned by this
    PostgreSQL role, not just the ones this instance exposes. ``_drop_database``
    itself must keep ignoring the allowlist: internal rollback callers
    (create/restore/duplicate cleanup) depend on it to remove a half-built
    database that was never exposed.

    The refusal *mechanism* is part of the contract, not an implementation
    detail: it raises ``AccessDenied`` and never returns ``False``, so the
    return value means exactly one thing. These tests asserted the older
    return-``False`` contract and kept passing until the behaviour changed
    under them, so both halves are pinned here."""

    def test_exp_drop_refuses_db_outside_allowlist(self):
        """Refusal RAISES; it does not return ``False``.

        That is what lets the return value mean one thing — ``False`` is "no
        such database".  It used to mean that OR "exists but is not exposed",
        which the web caller collapsed into ``Database %r was not found``,
        telling an operator a database they can see does not exist while
        ``exp_dump`` answered Access Denied for the same name.
        """
        with (
            mock.patch.object(db_service, "list_dbs", return_value=["exposed_db"]),
            mock.patch.object(db_service, "_drop_database") as drop_mock,
            self.assertLogs(db_service._logger, level="WARNING") as logs,
            self.assertRaises(odoo.exceptions.AccessDenied),
        ):
            db_service.exp_drop("other_db")
        drop_mock.assert_not_called()
        self.assertTrue(
            any("other_db" in msg for msg in logs.output),
            msg=f"expected a warning naming the rejected db, got: {logs.output}",
        )

    def test_exp_drop_refusal_is_indistinguishable_from_its_siblings(self):
        """``exp_dump``/``exp_rename``/``exp_duplicate_database`` all gate on
        ``check_db_exposed``, so an unexposed name must fail the same way through
        every one of them — otherwise the refusal itself leaks which databases
        exist."""
        with (
            mock.patch.object(db_service, "list_dbs", return_value=["exposed_db"]),
            self.assertRaises(odoo.exceptions.AccessDenied),
        ):
            db_service.check_db_exposed("other_db")

    def test_exp_drop_allows_db_in_allowlist(self):
        with (
            mock.patch.object(db_service, "list_dbs", return_value=["exposed_db"]),
            mock.patch.object(
                db_service, "_drop_database", return_value=True
            ) as drop_mock,
        ):
            result = db_service.exp_drop("exposed_db")
        self.assertTrue(result)
        drop_mock.assert_called_once_with("exposed_db")

    def test_drop_database_internal_ignores_allowlist(self):
        """A direct ``_drop_database`` call must never consult ``list_dbs`` —
        rollback paths (e.g. ``restore_db`` cleaning up a failed restore)
        drop databases that are, by construction, not in the allowlist yet."""
        with (
            mock.patch.object(db_service, "list_dbs") as list_dbs_mock,
            mock.patch("odoo.db.db_connect") as db_connect_mock,
        ):
            probe_cr = db_connect_mock.return_value.cursor.return_value
            probe_cr.fetchone.return_value = None
            result = db_service._drop_database("never_exposed_db")
        self.assertFalse(result)
        list_dbs_mock.assert_not_called()
