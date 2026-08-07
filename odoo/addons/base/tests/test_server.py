from types import SimpleNamespace

from odoo.service._helpers import over_memory_soft_limit
from odoo.tests.common import BaseCase


def _proc(rss):
    return SimpleNamespace(memory_info=lambda: SimpleNamespace(rss=rss))


class TestMemorySoftLimit(BaseCase):
    def test_disabled_limit_skips_the_proc_read(self):
        class Boom:
            def memory_info(self):
                raise AssertionError("RSS must not be read when the limit is 0")

        self.assertIsNone(over_memory_soft_limit(Boom(), 0))

    def test_under_limit_returns_none(self):
        self.assertIsNone(over_memory_soft_limit(_proc(100), 200))

    def test_at_limit_is_not_over(self):
        self.assertIsNone(over_memory_soft_limit(_proc(200), 200))

    def test_over_limit_returns_current_rss(self):
        self.assertEqual(over_memory_soft_limit(_proc(300), 200), 300)


class TestDbDispatchAuth(BaseCase):
    def test_master_password_set_is_subset_of_dispatch(self):
        from odoo.service import db

        self.assertLessEqual(
            db._REQUIRES_MASTER_PASSWORD,
            set(db._DISPATCH),
            "every password-gated method must be a real dispatch handler",
        )

    def test_destructive_methods_require_master_password(self):
        from odoo.service import db

        for method in (
            "create_database",
            "duplicate_database",
            "drop",
            "dump",
            "restore",
            "rename",
            "change_admin_password",
            "migrate_databases",
        ):
            self.assertIn(
                method,
                db._REQUIRES_MASTER_PASSWORD,
                f"{method!r} is destructive and must require the master password",
            )

    def test_public_methods_stay_unauthenticated(self):
        from odoo.service import db

        for method in (
            "db_exist",
            "list",
            "list_lang",
            "server_version",
            "list_countries",
        ):
            self.assertIn(method, db._DISPATCH)
            self.assertNotIn(
                method,
                db._REQUIRES_MASTER_PASSWORD,
                f"{method!r} is a public read and must not require the master password",
            )
