"""``Query`` and a limit of zero.

``_search`` admits ``0`` deliberately -- ``if limit is not None and limit is not
False`` -- and then ``Query.select`` tested ``if self.limit:`` and dropped it
again, so ``search(limit=0)`` asked for no rows and got every row. Measured on a
database before the fix: two partners in, two partners out.

The two layers have to agree, so the boundary is pinned here rather than left to
whichever of them is read first.
"""

import unittest

from odoo.libs.sql import SQL
from odoo.tools.query import Query


class RecordingEnv:
    """The one method `Query` calls on its env."""

    def __init__(self, rows=((0,),)):
        self.rows = rows
        self.queries = []

    def execute_query(self, sql):
        self.queries.append(sql.code)
        return list(self.rows)


class TestQueryLimit(unittest.TestCase):
    def make(self, **attrs):
        query = Query(RecordingEnv(), "res_partner")
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
        """A zero limit must survive into a subquery like any other."""
        self.assertIn("LIMIT", self.make(limit=0).subselect().code)

    def test_len_counts_through_a_zero_limit(self):
        query = self.make(limit=0)
        len(query)
        self.assertIn("LIMIT", query._env.queries[0])

    def test_set_result_ids_refuses_a_zero_limited_query(self):
        """A limit of 0 is a limit, so the query is not virgin."""
        with self.assertRaises(ValueError):
            self.make(limit=0).set_result_ids([1, 2])


class TestQueryIdInvalidation(unittest.TestCase):
    def test_an_empty_result_survives_narrowing(self):
        """Nothing a Query can add turns zero rows into more than zero."""
        query = Query(RecordingEnv(), "res_partner")
        query.set_result_ids([])
        self.assertTrue(query.is_empty())
        query.add_where(SQL("1=1"))
        self.assertTrue(query.is_empty())

    def test_a_non_empty_result_is_dropped(self):
        query = Query(RecordingEnv(), "res_partner")
        query._ids = (1, 2)
        query.add_where(SQL("1=1"))
        self.assertIsNone(query._ids)


if __name__ == "__main__":
    unittest.main()
