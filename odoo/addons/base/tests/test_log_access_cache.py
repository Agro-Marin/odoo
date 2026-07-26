"""``_write_multi``'s audit columns must not desynchronize the cache.

``_write_multi`` supplies ``write_uid``/``write_date`` for rows whose ``vals``
do not carry them -- a flush driven purely by a *computed* field, where no
``write()`` ran on the record.  Sending them to SQL without caching them left
``record.write_date`` stale for the rest of the transaction; ``env.cache.check()``
reported it on every run and, reporting only through ``_logger.warning``, could
never fail a build.
"""

from datetime import datetime

from odoo.tests.common import TransactionCase

BACKDATED = datetime(2020, 1, 1, 0, 0, 0)


class TestLogAccessCache(TransactionCase):
    """``write_uid``/``write_date`` written by ``_write_multi`` reach the cache."""

    def test_compute_driven_flush_keeps_write_date_cached(self):
        """A recompute-only flush must leave the cache agreeing with the row.

        ``cr.now()`` is fixed for the whole transaction, so a record created here
        already carries the timestamp the flush is about to write and the
        divergence cannot appear.  Backdating the row in SQL reproduces the real
        case -- a record written in an *earlier* transaction -- deterministically,
        without a clock dependency.
        """
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

        parent.name = "Parent Co Renamed"  # dirties child.complete_name only
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
        """A row with no values to write must not be UPDATEd for its audit columns.

        Backdated for the same reason as above: with the row already carrying
        this transaction's ``cr.now()``, a spurious UPDATE would rewrite the
        identical timestamp and stay invisible.
        """
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
        """``vals`` beats the injected audit values, and the cache keeps agreeing."""
        partner = self.env["res.partner"].create({"name": "Written"})
        self.env.flush_all()
        partner.write({"comment": "note"})
        self.env.flush_all()
        self.env.cache.check(self.env)
