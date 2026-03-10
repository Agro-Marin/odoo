"""Tests for web_save with optimistic locking (concurrency detection)."""

from datetime import datetime, timedelta

from odoo.exceptions import ConcurrencyError
from odoo.tests import common


@common.tagged("post_install", "-at_install", "web_unit", "web_save")
class TestWebSaveOptimisticLocking(common.TransactionCase):
    """Verify that web_save raises ConcurrencyError when the record has
    been modified by another user since the client last read it."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.partner = cls.env["res.partner"].create({"name": "Test Partner"})

    def test_web_save_without_locking(self):
        """web_save without last_write_date should work as before."""
        result = self.partner.web_save(
            {"name": "Updated"},
            specification={"name": {}},
        )
        self.assertEqual(result[0]["name"], "Updated")

    def test_web_save_with_matching_write_date(self):
        """web_save with matching last_write_date should succeed."""
        write_date = self.partner.write_date
        result = self.partner.web_save(
            {"name": "Updated Again"},
            specification={"name": {}},
            last_write_date=write_date.isoformat(),
        )
        self.assertEqual(result[0]["name"], "Updated Again")

    def test_web_save_with_stale_write_date(self):
        """web_save with stale last_write_date should raise ConcurrencyError."""
        # Simulate client reading at an earlier time
        stale_write_date = self.partner.write_date - timedelta(seconds=10)

        # Modify the record (simulates another user saving)
        self.partner.write({"name": "Changed by User A"})

        # Now try to save with the stale write_date
        with self.assertRaises(ConcurrencyError):
            self.partner.web_save(
                {"name": "Changed by User B"},
                specification={"name": {}},
                last_write_date=stale_write_date.isoformat(),
            )

    def test_web_save_create_ignores_locking(self):
        """web_save for creation should ignore last_write_date (no record to check)."""
        empty_recordset = self.env["res.partner"]
        result = empty_recordset.web_save(
            {"name": "New Partner"},
            specification={"name": {}},
            last_write_date="2020-01-01T00:00:00",
        )
        self.assertEqual(result[0]["name"], "New Partner")

    def test_web_save_concurrent_edit_preserves_first_save(self):
        """Full concurrency scenario: simulated concurrent modification.

        Within a TransactionCase all writes share the same transaction
        timestamp, so we simulate "another user" by directly advancing
        write_date in the DB before User B's save attempt.
        """
        # Client snapshot — what the user's browser saw when loading the form
        client_write_date = self.partner.write_date - timedelta(seconds=5)

        # Simulate that the server record was modified since the client read it
        # (another user saved, or a cron updated it)
        server_future = self.partner.write_date + timedelta(seconds=1)
        self.env.cr.execute(
            "UPDATE res_partner SET write_date = %s WHERE id = %s",
            (server_future, self.partner.id),
        )

        # User B tries to save with the outdated write_date — should fail
        with self.assertRaises(ConcurrencyError):
            self.partner.web_save(
                {"name": "User B Edit"},
                specification={"name": {}},
                last_write_date=client_write_date.isoformat(),
            )
