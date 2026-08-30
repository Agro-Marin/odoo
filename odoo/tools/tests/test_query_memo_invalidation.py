import unittest
from typing import TYPE_CHECKING, cast

from odoo.libs.sql import SQL
from odoo.tools.query import Query

if TYPE_CHECKING:
    from odoo.api import Environment


class _StubEnv:
    def __init__(self, rows=((1,), (2,), (3,))):
        self.rows = list(rows)
        self.queries = []

    def execute_query(self, sql):
        self.queries.append(sql)
        return self.rows


class TestQueryMemoInvalidation(unittest.TestCase):
    def _memoized(self):
        query = Query(cast("Environment", _StubEnv()), "res_partner")
        query.set_result_ids([1, 2, 3])
        self.assertEqual(query._ids, (1, 2, 3))
        return query

    def test_limit_invalidates_memo(self):
        query = self._memoized()
        query.limit = 1
        self.assertIsNone(query._ids)

    def test_offset_invalidates_memo(self):
        query = self._memoized()
        query.offset = 2
        self.assertIsNone(query._ids)

    def test_order_invalidates_memo(self):
        query = self._memoized()
        query.order = SQL('"res_partner"."name"')
        self.assertIsNone(query._ids)

    def test_groupby_invalidates_memo(self):
        query = self._memoized()
        query.groupby = SQL('"res_partner"."company_id"')
        self.assertIsNone(query._ids)

    def test_having_invalidates_memo(self):
        query = self._memoized()
        query.having = SQL("COUNT(*) > 1")
        self.assertIsNone(query._ids)

    def test_subselect_honours_a_limit_set_after_materialization(self):
        query = self._memoized()
        query.limit = 1

        sub = query.subselect()

        self.assertIn("LIMIT", sub.code)
        self.assertNotEqual(sub.params, (1, 2, 3))

    def test_subselect_uses_the_memo_while_the_shape_is_unchanged(self):
        query = self._memoized()
        sub = query.subselect()
        self.assertEqual(sub.code, "(%s, %s, %s)")
        self.assertEqual(sub.params, (1, 2, 3))

    def test_a_measured_empty_is_dropped_by_a_widening_limit(self):
        env = _StubEnv()
        query = Query(cast("Environment", env), "res_partner")
        query.limit = 0
        env.rows = []
        self.assertEqual(query.get_result_ids(), ())
        self.assertTrue(query.is_empty())

        query.limit = 10
        env.rows = [(1,), (2,), (3,)]
        self.assertEqual(query.get_result_ids(), (1, 2, 3))
        self.assertFalse(query.is_empty())
        self.assertTrue(bool(query))
        self.assertEqual(len(query), 3)

    def test_a_measured_empty_is_dropped_by_a_lowered_offset(self):
        env = _StubEnv(rows=[])
        query = Query(cast("Environment", env), "res_partner")
        query.offset = 99
        self.assertEqual(query.get_result_ids(), ())

        query.offset = 0
        env.rows = [(1,), (2,), (3,)]
        self.assertEqual(query.get_result_ids(), (1, 2, 3))

    def test_a_constructed_empty_needs_no_query_at_all(self):
        env = _StubEnv()
        query = Query(cast("Environment", env), "res_partner")
        query.set_result_ids([])
        query.limit = 5
        query.offset = 0
        self.assertTrue(query.is_empty())
        self.assertEqual(query.get_result_ids(), ())
        self.assertEqual(env.queries, [])

    def test_empty_memo_survives_a_shape_change(self):
        query = Query(cast("Environment", _StubEnv(rows=[])), "res_partner")
        query.set_result_ids([])
        self.assertTrue(query.is_empty())

        query.limit = 5
        self.assertTrue(query.is_empty())
        query.order = SQL('"res_partner"."id"')
        self.assertTrue(query.is_empty())

    def test_accessors_still_read_back_what_was_assigned(self):
        query = Query(cast("Environment", _StubEnv()), "res_partner")
        self.assertIsNone(query.limit)
        self.assertIsNone(query.offset)
        self.assertIsNone(query.groupby)
        self.assertIsNone(query.having)
        self.assertIsNone(query.order)

        query.limit = 7
        query.offset = 3
        query.groupby = SQL("a")
        query.having = SQL("b")
        query.order = SQL("c")

        self.assertEqual(query.limit, 7)
        self.assertEqual(query.offset, 3)
        self.assertEqual(query.groupby, SQL("a"))
        self.assertEqual(query.having, SQL("b"))
        self.assertEqual(query.order, SQL("c"))

        code = query.select().code
        self.assertIn("GROUP BY", code)
        self.assertIn("HAVING", code)
        self.assertIn("ORDER BY", code)
        self.assertIn("LIMIT", code)
        self.assertIn("OFFSET", code)

    def test_order_setter_still_coerces_a_string(self):
        query = Query(cast("Environment", _StubEnv()), "res_partner")
        query.order = SQL("id DESC")
        self.assertEqual(query.order, SQL("id DESC"))


if __name__ == "__main__":
    unittest.main()
