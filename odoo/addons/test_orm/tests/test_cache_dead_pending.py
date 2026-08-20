from odoo.tests import TransactionCase
from odoo.tools.misc import PENDING


class TestDeadPendingMarkers(TransactionCase):
    """`create` seeds PENDING for every stored computed field, meaning "a compute
    owes this record a value". A compute that leaves a record unassigned -- the
    idiom for "leave the stored value alone" -- returns without clearing the
    marker and without scheduling anything, so the value comes from the row
    instead. `_insert_cache` is a `setdefault`, so without help the marker
    outlives the SELECT that could have answered it and every further field read
    pays for another full-width SELECT of the same row.
    """

    def _record(self, mode):
        record = self.env["test_orm.partial.compute"].create({"mode": mode})
        self.env.flush_all()
        self.env.invalidate_all()
        return record.with_env(self.env)

    def _marker(self, record, fname):
        field = record._fields[fname]
        return field._get_cache(self.env).get(record.id, "<absent>")

    def _queries(self, func):
        before = self.env.cr.sql_log_count
        func()
        return self.env.cr.sql_log_count - before

    def test_one_fetch_answers_every_unassigned_field(self):
        record = self.env["test_orm.partial.compute"].create({"mode": "leave"})
        self.assertIs(self._marker(record, "beta"), PENDING, "create seeds the marker")
        self.env.flush_all()
        self.assertIs(
            self._marker(record, "beta"),
            PENDING,
            "the compute ran and assigned nothing, so the marker is now stale: "
            "nothing is scheduled to replace it",
        )

        first = self._queries(lambda: record.alpha)
        second = self._queries(lambda: record.beta)

        self.assertEqual(first, 1, "the first read pays for the row")
        self.assertEqual(
            second,
            0,
            "the row that answered alpha carries beta too, so a second SELECT "
            "means the marker outlived the fetch that could have cleared it",
        )
        self.assertEqual((record.alpha, record.beta), (0, 0))

    def test_a_compute_that_assigns_owns_its_value(self):
        record = self.env["test_orm.partial.compute"].create({"mode": "force"})
        self.assertEqual((record.alpha, record.beta), (1, 2))
        self.assertEqual(
            self._queries(lambda: (record.alpha, record.beta)),
            0,
            "an assigned compute needs no row at all",
        )

    def test_a_rescheduled_compute_keeps_its_marker(self):
        record = self._record("leave")
        record.alpha
        record.mode = "force"
        self.assertEqual(record.alpha, 1, "the compute, not the row, is authority")
        self.assertEqual(record.beta, 2)

    def test_a_pending_write_survives_a_fetch(self):
        record = self._record("leave")
        record.alpha = 42
        record.beta
        self.assertEqual(
            record.alpha, 42, "an unflushed write must not be replaced by the row"
        )

    def test_the_row_wins_only_once_nothing_else_owns_the_field(self):
        record = self._record("leave")
        self.env.cr.execute(
            "UPDATE test_orm_partial_compute SET beta = 7 WHERE id = %s", (record.id,)
        )
        record.alpha
        self.assertEqual(record.beta, 7, "the value taken is the one in the row")
