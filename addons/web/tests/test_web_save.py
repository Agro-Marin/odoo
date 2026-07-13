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
        self._server_set(parent_id=self.c2.id)
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

    # -- jsonb-backed columns (translated / company-dependent) fail open -----
    def test_translated_field_no_false_conflict(self):
        """Editing a translated field must not self-conflict: the raw DB value
        is a per-lang jsonb dict, never equal to the scalar the client read."""
        category = self.env["res.partner.category"].create({"name": "Original"})
        self.env.flush_all()
        self.assertTrue(category._fields["name"].translate)  # guard the premise
        category.web_save(
            {"name": "Renamed"}, specification={"name": {}},
            known_values={"name": "Original"},
        )
        self.assertEqual(category.name, "Renamed")

    def test_translated_field_fails_open(self):
        """A genuine concurrent change to a translated field is NOT detected
        (fail open): the jsonb dict cannot be safely compared to the client's
        scalar baseline, so the field is skipped rather than false-conflict."""
        category = self.env["res.partner.category"].create({"name": "Original"})
        self.env.flush_all()
        self.env.cr.execute(
            "UPDATE res_partner_category SET name = %s WHERE id = %s",
            ('{"en_US": "Changed Elsewhere"}', category.id),
        )
        category.web_save(
            {"name": "Renamed"}, specification={"name": {}},
            known_values={"name": "Original"},
        )
        self.assertEqual(category.name, "Renamed")

    # -- legacy row-level fallback still works -------------------------------
    def test_legacy_last_write_date_fallback(self):
        stale = self.partner.write_date - timedelta(seconds=10)
        self._server_set(write_date=self.partner.write_date + timedelta(seconds=5))
        with self.assertRaises(UserError):
            self.partner.web_save(
                {"phone": "222"}, specification={"phone": {}},
                last_write_date=stale.isoformat(),
            )

    # -- multi-record web_save (list view mass-edit) -------------------------
    def test_multirecord_web_save_writes_all(self):
        """web_save on a multi-record set writes every record: the list view
        mass-edit calls web_save with several ids and no concurrency args."""
        recs = self.c1 + self.c2
        result = recs.web_save({"phone": "9"}, specification={"phone": {}})
        self.assertEqual([r["phone"] for r in result], ["9", "9"])
        self.assertEqual(recs.mapped("phone"), ["9", "9"])

    def test_multirecord_web_save_rejects_last_write_date(self):
        """The legacy last_write_date path reads ``self.id`` and is single-record
        only: a multi-record caller using it must fail the singleton check."""
        recs = self.c1 + self.c2
        with self.assertRaises(ValueError):
            recs.web_save(
                {"phone": "9"}, specification={"phone": {}},
                last_write_date="2020-01-01T00:00:00.000Z",
            )

    # -- multi-record field-scoped locking (list mass-edit) ------------------

    def _server_set_on(self, record, **col_vals):
        """Commit a change to ``record`` at the DB level (concurrent worker)."""
        for col, val in col_vals.items():
            self.env.cr.execute(
                'UPDATE res_partner SET "%s" = %%s WHERE id = %%s' % col,
                (val, record.id),
            )

    def test_multirecord_known_values_conflict(self):
        """Mass-edit rejects when ANY selected record was changed on the field
        being written, and each record is checked against its OWN baseline.
        Only c2 conflicts here — c1/c3 baselines match their real state."""
        recs = self.c1 + self.c2 + self.c3
        # Give the three a known starting phone, then let another user change c2.
        self.c1.phone = self.c2.phone = self.c3.phone = "start"
        self.env.flush_all()
        self._server_set_on(self.c2, phone="999")
        with self.assertRaises(UserError):
            recs.web_save(
                {"phone": "new"},
                specification={"phone": {}},
                known_values={
                    self.c1.id: {"phone": "start"},
                    self.c2.id: {"phone": "start"},  # baseline start, server 999
                    self.c3.id: {"phone": "start"},
                },
            )
        # The check raised before write(): nothing was persisted.
        self.env.cr.execute(
            "SELECT phone FROM res_partner WHERE id = %s", (self.c1.id,)
        )
        self.assertEqual(self.env.cr.fetchone()[0], "start")

    def test_multirecord_known_values_no_conflict(self):
        """Mass-edit succeeds when no selected record's written field was
        concurrently changed away from its baseline."""
        recs = self.c1 + self.c2
        result = recs.web_save(
            {"phone": "same"},
            specification={"phone": {}},
            known_values={
                self.c1.id: {"phone": self.c1.phone or False},
                self.c2.id: {"phone": self.c2.phone or False},
            },
        )
        self.assertEqual([r["phone"] for r in result], ["same", "same"])

    def test_multirecord_disjoint_change_no_conflict(self):
        """A concurrent change to a DIFFERENT field than the one being mass-
        edited is ignored (disjoint columns, no lost update)."""
        recs = self.c1 + self.c2
        self._server_set_on(self.c2, function="changed-by-other")
        # We mass-edit phone; the concurrent change was to function.
        recs.web_save(
            {"phone": "999"},
            specification={"phone": {}},
            known_values={
                self.c1.id: {"phone": self.c1.phone or False},
                self.c2.id: {"phone": self.c2.phone or False},
            },
        )
        self.assertEqual(recs.mapped("phone"), ["999", "999"])

    def test_multirecord_missing_baseline_fails_open(self):
        """A record with no baseline entry is skipped (fail open) — its
        concurrent change does not block the batch."""
        recs = self.c1 + self.c2
        self._server_set_on(self.c2, phone="concurrent")
        # Only c1 has a baseline; c2 is unchecked and must not raise.
        recs.web_save(
            {"phone": "999"},
            specification={"phone": {}},
            known_values={self.c1.id: {"phone": self.c1.phone or False}},
        )
        self.assertEqual(recs.mapped("phone"), ["999", "999"])

    def test_multirecord_same_value_no_conflict(self):
        """No conflict when the concurrent change landed on the SAME value the
        user is writing anyway."""
        recs = self.c1 + self.c2
        self._server_set_on(self.c2, phone="target")
        result = recs.web_save(
            {"phone": "target"},
            specification={"phone": {}},
            known_values={
                self.c1.id: {"phone": self.c1.phone or False},
                self.c2.id: {"phone": "old"},  # server now "target" == new
            },
        )
        self.assertEqual([r["phone"] for r in result], ["target", "target"])

    def test_single_selected_row_massedit_still_checked(self):
        """A list mass-edit of exactly ONE selected row sends the per-record
        shape ``{id: {field: baseline}}`` (dynamic_list._multiSave always does,
        regardless of selection size). The server must key off the SHAPE, not
        ``len(self) == 1`` — otherwise the record-id key matches no field name
        in the singleton path and the concurrency guard silently no-ops,
        losing a concurrent edit. Regression: this must still raise."""
        self._server_set_on(self.c1, phone="999")
        with self.assertRaises(UserError):
            self.c1.web_save(
                {"phone": "new"},
                specification={"phone": {}},
                known_values={self.c1.id: {"phone": "start"}},  # server moved to 999
            )
        # Nothing persisted — the guard raised before write().
        self.env.cr.execute(
            "SELECT phone FROM res_partner WHERE id = %s", (self.c1.id,)
        )
        self.assertEqual(self.env.cr.fetchone()[0], "999")

    def test_single_selected_row_massedit_no_false_conflict(self):
        """The single-row per-record shape must also NOT false-conflict when the
        baseline matches the server's current value."""
        self.c1.phone = "start"
        self.env.flush_all()
        result = self.c1.web_save(
            {"phone": "new"},
            specification={"phone": {}},
            known_values={self.c1.id: {"phone": "start"}},
        )
        self.assertEqual(result[0]["phone"], "new")

    # -- web_save_multi: per-record vals (relative Field Operation path) ------
    # Unlike the mass-edit web_save (same vals to every record), web_save_multi
    # carries a DISTINCT vals per record, so each is checked against its own
    # vals AND its own baseline.

    def test_web_save_multi_writes_all_no_locking(self):
        """Without known_values, web_save_multi writes each record's own vals."""
        recs = self.c1 + self.c2
        result = recs.web_save_multi(
            [{"phone": "a1"}, {"phone": "a2"}],
            specification={"phone": {}},
        )
        self.assertEqual([r["phone"] for r in result], ["a1", "a2"])
        self.assertEqual(recs.mapped("phone"), ["a1", "a2"])

    def test_web_save_multi_per_record_no_conflict(self):
        """Distinct per-record vals save when no record's field moved on the
        server since it was read."""
        recs = self.c1 + self.c2
        result = recs.web_save_multi(
            [{"phone": "a1"}, {"phone": "a2"}],
            specification={"phone": {}},
            known_values={
                self.c1.id: {"phone": self.c1.phone or False},
                self.c2.id: {"phone": self.c2.phone or False},
            },
        )
        self.assertEqual([r["phone"] for r in result], ["a1", "a2"])

    def test_web_save_multi_per_record_conflict(self):
        """web_save_multi rejects when a record's written field was changed on
        the server since its own baseline was read; nothing is persisted."""
        recs = self.c1 + self.c2
        self.c1.phone = self.c2.phone = "start"
        self.env.flush_all()
        self._server_set_on(self.c2, phone="999")  # another user moved c2
        with self.assertRaises(UserError):
            recs.web_save_multi(
                [{"phone": "a1"}, {"phone": "a2"}],
                specification={"phone": {}},
                known_values={
                    self.c1.id: {"phone": "start"},
                    self.c2.id: {"phone": "start"},  # server 999 != start, != a2
                },
            )
        # The check raised before any write(): nothing was persisted.
        self.env.cr.execute(
            "SELECT phone FROM res_partner WHERE id = %s", (self.c1.id,)
        )
        self.assertEqual(self.env.cr.fetchone()[0], "start")

    def test_web_save_multi_same_value_no_conflict(self):
        """No conflict when the concurrent change happens to equal the absolute
        value THIS record is writing (the leniency is per-record vals)."""
        recs = self.c1 + self.c2
        self._server_set_on(self.c2, phone="a2")  # server == c2's own new value
        result = recs.web_save_multi(
            [{"phone": "a1"}, {"phone": "a2"}],
            specification={"phone": {}},
            known_values={
                self.c1.id: {"phone": self.c1.phone or False},
                self.c2.id: {"phone": "old"},  # baseline old, server a2 == new
            },
        )
        self.assertEqual([r["phone"] for r in result], ["a1", "a2"])

    def test_web_save_multi_missing_baseline_fails_open(self):
        """A record with no baseline entry is skipped (fail open) — its
        concurrent change does not block the batch."""
        recs = self.c1 + self.c2
        self._server_set_on(self.c2, phone="concurrent")
        recs.web_save_multi(
            [{"phone": "a1"}, {"phone": "a2"}],
            specification={"phone": {}},
            known_values={self.c1.id: {"phone": self.c1.phone or False}},
        )
        self.assertEqual(recs.mapped("phone"), ["a1", "a2"])
