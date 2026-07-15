from unittest import mock

from odoo.service import db as db_service
from odoo.tests import BaseCase


class TestExpDropAllowlist(BaseCase):
    """``exp_drop`` must refuse to drop a database outside ``list_dbs(True)``
    — the RPC entry point is reachable with only the master password, so
    without this gate a caller could ``DROP DATABASE`` any DB owned by this
    PostgreSQL role, not just the ones this instance exposes. ``_drop_database``
    itself must keep ignoring the allowlist: internal rollback callers
    (create/restore/duplicate cleanup) depend on it to remove a half-built
    database that was never exposed."""

    def test_exp_drop_refuses_db_outside_allowlist(self):
        with (
            mock.patch.object(db_service, "list_dbs", return_value=["exposed_db"]),
            mock.patch.object(db_service, "_drop_database") as drop_mock,
            self.assertLogs(db_service._logger, level="WARNING") as logs,
        ):
            result = db_service.exp_drop("other_db")
        self.assertFalse(result)
        drop_mock.assert_not_called()
        self.assertTrue(
            any("other_db" in msg for msg in logs.output),
            msg=f"expected a warning naming the rejected db, got: {logs.output}",
        )

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
            # closing(probe.cursor()) binds the cursor itself, not __enter__()'s
            # return value -- closing() is a plain wrapper, not a context
            # manager implemented by the cursor.
            probe_cr = db_connect_mock.return_value.cursor.return_value
            probe_cr.fetchone.return_value = None  # DB genuinely absent -> False
            result = db_service._drop_database("never_exposed_db")
        self.assertFalse(result)
        list_dbs_mock.assert_not_called()
