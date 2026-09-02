import unittest

from odoo.db.metrics import categorize_query


class TestCategorizeQuery(unittest.TestCase):
    def test_select_from(self):
        qtype, table = categorize_query("SELECT * FROM res_users")
        self.assertEqual(qtype, "from")
        self.assertEqual(table, "res_users")

    def test_insert_into(self):
        qtype, table = categorize_query("INSERT INTO res_users (name) VALUES ('x')")
        self.assertEqual(qtype, "into")
        self.assertEqual(table, "res_users")

    def test_insert_select_prioritizes_into(self):
        qtype, table = categorize_query("INSERT INTO t1 SELECT * FROM t2")
        self.assertEqual(qtype, "into")
        self.assertEqual(table, "t1")

    def test_update_is_a_write(self):
        qtype, table = categorize_query("UPDATE res_users SET name='x'")
        self.assertEqual(qtype, "into")
        self.assertEqual(table, "res_users")

    def test_update_schema_qualified(self):
        qtype, table = categorize_query('UPDATE "public"."res_users" SET name=1')
        self.assertEqual(qtype, "into")
        self.assertEqual(table, "res_users")

    def test_update_with_from_subquery(self):
        qtype, table = categorize_query(
            "UPDATE t1 SET a = s.a FROM (SELECT * FROM t2) s WHERE s.id = t1.id"
        )
        self.assertEqual(qtype, "into")
        self.assertEqual(table, "t1")

    def test_delete_is_a_write(self):
        qtype, table = categorize_query("DELETE FROM res_users WHERE id = 1")
        self.assertEqual(qtype, "into")
        self.assertEqual(table, "res_users")

    def test_select_for_update_stays_a_read(self):
        qtype, table = categorize_query(
            "SELECT id FROM res_users WHERE id = 1 FOR UPDATE NOWAIT"
        )
        self.assertEqual(qtype, "from")
        self.assertEqual(table, "res_users")

    def test_other(self):
        qtype, table = categorize_query("COMMIT")
        self.assertEqual(qtype, "other")
        self.assertIsNone(table)

    def test_quoted_table_name(self):
        qtype, table = categorize_query('SELECT * FROM "my_table" WHERE id = 1')
        self.assertEqual(qtype, "from")
        self.assertEqual(table, "my_table")

    def test_case_insensitive(self):
        qtype, table = categorize_query("select * from RES_USERS")
        self.assertEqual(qtype, "from")
        self.assertEqual(table, "RES_USERS")

    def test_multiline_query(self):
        qtype, table = categorize_query("SELECT id\n  FROM res_partner\n WHERE active")
        self.assertEqual(qtype, "from")
        self.assertEqual(table, "res_partner")


class TestFromInsideAFunctionCall(unittest.TestCase):
    def test_extract_does_not_shadow_the_real_from(self):
        qtype, table = categorize_query(
            "SELECT extract(epoch FROM now() - x) FROM res_partner"
        )
        self.assertEqual((qtype, table), ("from", "res_partner"))

    def test_substring_and_trim_do_not_shadow_it_either(self):
        for query in (
            "SELECT substring(x FROM 2) FROM t",
            "SELECT trim(BOTH ' ' FROM x) FROM t",
        ):
            self.assertEqual(categorize_query(query), ("from", "t"), query)

    def test_a_statement_with_no_from_clause_names_no_table(self):
        from odoo.db.lag import LAG_SQL

        self.assertEqual(
            categorize_query(LAG_SQL),
            ("other", None),
            "the replica lag probe has no FROM clause; reaching into a "
            "function's arguments for one is how `now` became a table",
        )

    def test_a_from_clause_subquery_still_names_the_inner_table(self):
        self.assertEqual(
            categorize_query("SELECT a FROM (SELECT b FROM inner_t) s"),
            ("from", "inner_t"),
            "masking must not let the FROM match run through the hole and "
            "capture the alias instead",
        )

    def test_delete_with_a_subquery_names_the_deleted_table(self):
        self.assertEqual(
            categorize_query("DELETE FROM res_partner WHERE id IN (SELECT id FROM o)"),
            ("into", "res_partner"),
        )
