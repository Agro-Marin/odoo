import unittest
from typing import TYPE_CHECKING, cast

from odoo.libs.sql import SQL
from odoo.tools.query import Query

if TYPE_CHECKING:
    from odoo.api import Environment


class RecordingEnv:
    def __init__(self, rows=((0,),)):
        self.rows = rows
        self.queries = []

    def execute_query(self, sql):
        self.queries.append(sql.code)
        return list(self.rows)


class TestQueryLimit(unittest.TestCase):
    def make(self, **attrs):
        query = Query(cast("Environment", RecordingEnv()), "res_partner")
        for name, value in attrs.items():
            setattr(query, name, value)
        return query

    def test_limit_zero_emits_a_limit(self):
        self.assertIn("LIMIT", self.make(limit=0).select().code)

    def test_limit_none_emits_no_limit(self):
        self.assertNotIn("LIMIT", self.make(limit=None).select().code)

    def test_limit_positive_emits_a_limit(self):
        self.assertIn("LIMIT", self.make(limit=5).select().code)

    def test_limit_zero_is_carried_as_a_parameter(self):
        self.assertIn(0, self.make(limit=0).select().params)

    def test_subselect_wraps_a_zero_limit(self):
        self.assertIn("LIMIT", self.make(limit=0).subselect().code)

    def test_len_counts_through_a_zero_limit(self):
        query = self.make(limit=0)
        len(query)
        self.assertIn("LIMIT", query._env.queries[0])

    def test_count_matching_honours_a_zero_limit(self):
        # `if limit:` sent a zero down the unlimited branch, so count_matching
        # answered the full count for an input __len__ answers 0 for.
        query = self.make()
        query.count_matching(limit=0)
        self.assertIn("LIMIT", query._env.queries[-1])

    def test_count_matching_without_a_limit_emits_none(self):
        query = self.make()
        query.count_matching()
        self.assertNotIn("LIMIT", query._env.queries[-1])

    def test_set_result_ids_refuses_a_zero_limited_query(self):
        with self.assertRaises(ValueError):
            self.make(limit=0).set_result_ids([1, 2])


class TestQueryIdInvalidation(unittest.TestCase):
    def test_an_empty_result_survives_narrowing(self):
        query = Query(cast("Environment", RecordingEnv()), "res_partner")
        query.set_result_ids([])
        self.assertTrue(query.is_empty())
        query.add_where(SQL("1=1"))
        self.assertTrue(query.is_empty())

    def test_a_non_empty_result_is_dropped(self):
        query = Query(cast("Environment", RecordingEnv()), "res_partner")
        query._ids = (1, 2)
        query.add_where(SQL("1=1"))
        self.assertIsNone(query._ids)


if __name__ == "__main__":
    unittest.main()
