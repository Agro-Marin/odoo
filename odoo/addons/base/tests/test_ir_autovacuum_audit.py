from odoo.exceptions import AccessDenied
from odoo.tests.common import TransactionCase, new_test_user, tagged


@tagged("post_install", "-at_install")
class TestAutovacuumDispatcher(TransactionCase):
    """Regression coverage for the ir.autovacuum dispatcher guard (audit AV-T1).

    ``_run_vacuum_cleaner`` requires ``is_admin()`` AND a ``cron_id`` in context
    (ir_autovacuum.py:31-32), otherwise it raises ``AccessDenied``.

    The failure-isolation contract (one ``@api.autovacuum`` method raising must
    not abort the others) is NOT covered here: exercising it requires running
    the dispatch loop, which commits the cursor between methods -- forbidden
    inside a TransactionCase. The happy path is already covered in test_orm.
    """

    def test_run_vacuum_requires_cron_id_in_context(self):
        """As superuser/admin but without cron_id in context -> AccessDenied."""
        autovacuum = self.env["ir.autovacuum"]
        self.assertTrue(autovacuum.env.is_admin())
        self.assertFalse(autovacuum.env.context.get("cron_id"))
        with self.assertRaises(AccessDenied):
            autovacuum._run_vacuum_cleaner()

    def test_run_vacuum_requires_admin(self):
        """A non-admin user, even with cron_id in context, is rejected."""
        user = new_test_user(self.env, login="av_plain_user")
        autovacuum = self.env["ir.autovacuum"].with_user(user).with_context(cron_id=1)
        self.assertFalse(autovacuum.env.is_admin())
        self.assertTrue(autovacuum.env.context.get("cron_id"))
        with self.assertRaises(AccessDenied):
            autovacuum._run_vacuum_cleaner()
