from datetime import datetime

from odoo.tests.common import TransactionCase

BACKDATED = datetime(2020, 1, 1, 0, 0, 0)


class TestLogAccessCache(TransactionCase):
    def test_compute_driven_flush_keeps_write_date_cached(self):
        Partner = self.env["res.partner"]
        parent = Partner.create({"name": "Parent Co", "is_company": True})
        child = Partner.create({"name": "Child", "parent_id": parent.id})
        self.env.flush_all()

        self.env.cr.execute(
            "UPDATE res_partner SET write_date = %s WHERE id = %s",
            (BACKDATED, child.id),
        )
        child.invalidate_recordset(["write_date"])
        self.assertEqual(child.write_date, BACKDATED)

        parent.name = "Parent Co Renamed"
        self.env.flush_all()

        self.env.cr.execute(
            "SELECT write_date, write_uid FROM res_partner WHERE id = %s", (child.id,)
        )
        db_write_date, db_write_uid = self.env.cr.fetchone()
        self.assertNotEqual(db_write_date, BACKDATED, "the flush must bump the row")
        self.assertEqual(child.write_date, db_write_date)
        self.assertEqual(child.write_uid.id, db_write_uid)
        self.env.cache.check(self.env)

    def test_empty_values_write_nothing(self):
        partner = self.env["res.partner"].create({"name": "Untouched"})
        self.env.flush_all()
        self.env.cr.execute(
            "UPDATE res_partner SET write_date = %s WHERE id = %s",
            (BACKDATED, partner.id),
        )

        partner._write_multi([{}])

        self.env.cr.execute(
            "SELECT write_date FROM res_partner WHERE id = %s", (partner.id,)
        )
        self.assertEqual(self.env.cr.fetchone()[0], BACKDATED)

    def test_explicit_write_values_win_and_stay_cached(self):
        partner = self.env["res.partner"].create({"name": "Written"})
        self.env.flush_all()
        partner.write({"comment": "note"})
        self.env.flush_all()
        self.env.cache.check(self.env)
