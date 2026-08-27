from datetime import datetime, timedelta

from odoo.tests import common


class TestAutovacuum(common.TransactionCase):
    def test_api_autovacuum(self):
        Model = self.env["test_orm.autovacuumed"]
        instance = Model.create({"expire_at": datetime.now() - timedelta(days=15)})
        self.assertTrue(instance.exists())

        with self.enter_registry_test_mode():
            self.env.ref("base.autovacuum_job").method_direct_trigger()

        self.assertFalse(instance.exists())

    def test_gc_proper_respects_the_limit_and_reports_remaining(self):
        # _gc_proper demonstrates the (done, remaining) batching/re-queue
        # protocol consumed by ir.autovacuum._run_vacuum_cleaner: called
        # directly (not via the cron, which would also run _gc_simple and
        # delete everything unconditionally, masking the limit behavior).
        Model = self.env["test_orm.autovacuumed"]
        expired = Model.create(
            [{"expire_at": datetime.now() - timedelta(days=15)} for _ in range(8)]
        )
        self.env.flush_all()

        done, has_more = Model._gc_proper(limit=5)

        self.assertEqual(done, 5, "must delete exactly `limit` records per call")
        self.assertTrue(has_more, "must report more work remains past the limit")
        self.assertEqual(len(expired.exists()), 3, "the other 3 must survive")

        done, has_more = Model._gc_proper(limit=5)

        self.assertEqual(done, 3, "the second call clears the remainder")
        self.assertFalse(has_more, "must report no work remains")
        self.assertFalse(expired.exists())
