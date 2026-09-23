from odoo.tests.common import TransactionCase


class TestRecursiveRecomputeReadsItsOldValueOnce(TransactionCase):
    def _cost_of_recomputing(self, count):
        group = self.env["test_orm.recursive.keep.group"].create({"value": "first"})
        records = self.env["test_orm.recursive.keep"].create(
            [{"group_id": group.id} for _ in range(count)]
        )
        self.assertEqual(set(records.mapped("label")), {"first"})
        self.env.flush_all()
        self.env.invalidate_all()
        before = self.env.cr.sql_statement_count
        group.value = "second"
        records.mapped("label")
        self.env.flush_all()
        cost = self.env.cr.sql_statement_count - before
        self.assertEqual(set(records.mapped("label")), {"first"})
        return cost

    def test_the_cost_does_not_grow_with_the_records_recomputed(self):
        self.assertEqual(self._cost_of_recomputing(25), self._cost_of_recomputing(5))
