import unittest
from types import SimpleNamespace
from unittest import mock

from odoo.service import db as db_service
from odoo.service._helpers import over_memory_soft_limit


def _proc(rss):
    return SimpleNamespace(memory_info=lambda: SimpleNamespace(rss=rss))


class TestMemorySoftLimit(unittest.TestCase):
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


class TestInternalDropIsUngated(unittest.TestCase):
    def test_drop_database_internal_ignores_allowlist(self):
        with (
            mock.patch.object(db_service.listing, "list_dbs") as list_dbs_mock,
            mock.patch("odoo.db.db_connect") as db_connect_mock,
        ):
            probe_cr = db_connect_mock.return_value.cursor.return_value
            probe_cr.fetchone.return_value = None
            result = db_service._drop_database("never_exposed_db")
        self.assertFalse(result)
        list_dbs_mock.assert_not_called()
