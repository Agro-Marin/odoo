from odoo.tests.common import TransactionCase


class TestComputeCheckDeferral(TransactionCase):
    def test_a_nested_compute_checks_its_constraints_after_the_outer_one_assigns(self):
        record = self.env["test_orm.compute_check"].create({"name": "a"})
        self.assertEqual(record.code, "A")
        self.assertEqual(record.label, "a")

    def test_a_deferred_check_skips_a_record_deleted_before_it_runs(self):
        record = self.env["test_orm.compute_check"].create({"name": "a"})
        self.env.flush_all()
        field = record._fields["label"]
        with self.env.protecting([record._fields["code"]], record):
            record._check_computed(field)
            record.unlink()

    def test_a_deferred_check_keeps_the_value_the_outer_compute_assigned(self):
        host = self.env["test_orm.compute_check_host"].create({"name": "a"})
        self.assertTrue(host.has_code)
        self.assertTrue(host.lines_made)
        self.assertEqual(len(host.line_ids), 1)
