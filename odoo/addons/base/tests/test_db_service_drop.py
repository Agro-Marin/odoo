from unittest import mock

import odoo
from odoo.service import db as db_service
from odoo.tests import BaseCase


class TestExpDropAllowlist(BaseCase):
    def test_exp_drop_refuses_db_outside_allowlist(self):
        with (
            mock.patch.object(
                db_service.listing, "list_dbs", return_value=["exposed_db"]
            ),
            mock.patch.object(db_service.lifecycle, "_drop_database") as drop_mock,
            # The channel, not a module attribute: every module in the
            # odoo.service.db package logs to "odoo.service.db" by design
            # (ADR-0014), so the name is the stable thing to assert on.
            self.assertLogs("odoo.service.db", level="WARNING") as logs,
            self.assertRaises(odoo.exceptions.AccessDenied),
        ):
            db_service.exp_drop("other_db")
        drop_mock.assert_not_called()
        self.assertTrue(
            any("other_db" in msg for msg in logs.output),
            msg=f"expected a warning naming the rejected db, got: {logs.output}",
        )

    def test_exp_drop_refusal_is_indistinguishable_from_its_siblings(self):
        with (
            mock.patch.object(
                db_service.listing, "list_dbs", return_value=["exposed_db"]
            ),
            self.assertRaises(odoo.exceptions.AccessDenied),
        ):
            db_service.check_db_exposed("other_db")

    def test_exp_drop_allows_db_in_allowlist(self):
        with (
            mock.patch.object(
                db_service.listing, "list_dbs", return_value=["exposed_db"]
            ),
            mock.patch.object(
                db_service.lifecycle, "_drop_database", return_value=True
            ) as drop_mock,
        ):
            result = db_service.exp_drop("exposed_db")
        self.assertTrue(result)
        drop_mock.assert_called_once_with("exposed_db")

    def test_drop_database_internal_ignores_allowlist(self):
        with (
            mock.patch.object(db_service.listing, "list_dbs") as list_dbs_mock,
            mock.patch("odoo.db.db_connect") as db_connect_mock,
        ):
            probe_cr = db_connect_mock.return_value.cursor.return_value
            probe_cr.fetchone.return_value = None
            result = db_service._drop_database("never_exposed_db")
        self.assertFalse(result)
        list_dbs_mock.assert_not_called()
