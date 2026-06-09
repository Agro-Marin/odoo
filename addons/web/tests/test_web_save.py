"""Tests for web_save optimistic locking (field-scoped concurrency detection).

The field-scoped check raises ``UserError`` only when a field the user is
writing was changed on the server since the client read it.  Concurrent writes
to *other* fields (e.g. stored-compute recomputations triggered by related
records) touch disjoint columns and must NOT block the save.
"""

from datetime import timedelta

from odoo.exceptions import UserError
from odoo.tests import common


@common.tagged("post_install", "-at_install", "web_unit", "web_save")
class TestWebSaveOptimisticLocking(common.TransactionCase):
    """Field-scoped optimistic locking in web_save."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.c1 = cls.env["res.partner"].create({"name": "Company 1", "is_company": True})
        cls.c2 = cls.env["res.partner"].create({"name": "Company 2", "is_company": True})
        cls.c3 = cls.env["res.partner"].create({"name": "Company 3", "is_company": True})
        cls.partner = cls.env["res.partner"].create({
            "name": "Base Partner",
            "phone": "111",
            "function": "f0",
            "parent_id": cls.c1.id,
        })
        cls.env.flush_all()  # ensure the DB holds these values for raw reads

    def _server_set(self, **col_vals):
        """Simulate another transaction committing a change, at the DB level
        (bypasses the ORM cache, exactly like a concurrent worker would)."""
        for col, val in col_vals.items():
            self.env.cr.execute(
                'UPDATE res_partner SET "%s" = %%s WHERE id = %%s' % col,
                (val, self.partner.id),
            )

    # -- no concurrency args: behaves as an ordinary save --------------------
    def test_no_concurrency_args(self):
        result = self.partner.web_save({"phone": "x"}, specification={"phone": {}})
        self.assertEqual(result[0]["phone"], "x")

    def test_create_ignores_locking(self):
        result = self.env["res.partner"].web_save(
            {"name": "New"}, specification={"name": {}},
            known_values={"name": "anything"},
        )
        self.assertEqual(result[0]["name"], "New")

    # -- field-scoped: the core behaviour ------------------------------------
    def test_disjoint_change_does_not_conflict(self):
        """A concurrent change to a DIFFERENT field must not block the save."""
        self._server_set(function="changed-by-other")
        self.partner.web_save(
            {"phone": "222"}, specification={"phone": {}},
            known_values={"phone": "111"},
        )
        self.assertEqual(self.partner.phone, "222")

    def test_same_field_conflict(self):
        """A concurrent change to the SAME field the user edits -> UserError."""
        self._server_set(phone="999")
        with self.assertRaises(UserError):
            self.partner.web_save(
                {"phone": "222"}, specification={"phone": {}},
                known_values={"phone": "111"},
            )

    def test_same_field_same_value_no_conflict(self):
        """If the server already holds the value the user is writing, no loss."""
        self._server_set(phone="222")
        self.partner.web_save(
            {"phone": "222"}, specification={"phone": {}},
            known_values={"phone": "111"},
        )
        self.assertEqual(self.partner.phone, "222")

    def test_many2one_conflict(self):
        """Concurrent reassignment of a many2one the user also edits -> error."""
        self._server_set(parent_id=self.c2.id)
        with self.assertRaises(UserError):
            self.partner.web_save(
                {"parent_id": self.c3.id}, specification={"parent_id": {}},
                known_values={"parent_id": {"id": self.c1.id, "display_name": "Company 1"}},
            )

    def test_many2one_user_change_no_conflict(self):
        """User reassigns a many2one nobody else touched -> no conflict."""
        self.partner.web_save(
            {"parent_id": self.c3.id}, specification={"parent_id": {}},
            known_values={"parent_id": {"id": self.c1.id, "display_name": "Company 1"}},
        )
        self.assertEqual(self.partner.parent_id, self.c3)

    def test_only_written_fields_are_checked(self):
        """A baseline for a field NOT being written is ignored (only vals count)."""
        self._server_set(parent_id=self.c2.id)  # changed, but user isn't writing it
        self.partner.web_save(
            {"phone": "222"}, specification={"phone": {}},
            known_values={
                "phone": "111",
                "parent_id": {"id": self.c1.id, "display_name": "Company 1"},
            },
        )
        self.assertEqual(self.partner.phone, "222")

    def test_empty_known_values_skips_check(self):
        """No comparable baselines (e.g. x2many-only edit) -> never blocks."""
        self._server_set(phone="999")
        self.partner.web_save(
            {"phone": "222"}, specification={"phone": {}},
            known_values={},
        )
        self.assertEqual(self.partner.phone, "222")

    # -- legacy row-level fallback still works -------------------------------
    def test_legacy_last_write_date_fallback(self):
        stale = self.partner.write_date - timedelta(seconds=10)
        self._server_set(write_date=self.partner.write_date + timedelta(seconds=5))
        with self.assertRaises(UserError):
            self.partner.web_save(
                {"phone": "222"}, specification={"phone": {}},
                last_write_date=stale.isoformat(),
            )
