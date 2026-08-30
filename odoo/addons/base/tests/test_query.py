from odoo.tests.common import BaseCase, TransactionCase
from odoo.tools import SQL, Query


class QueryTestCase(BaseCase):
    def test_basic_query(self):
        query = Query(None, "product_product")
        query.add_table("product_template")
        query.add_where(SQL("product_product.template_id = product_template.id"))
        alias = query.join(
            "product_template", "categ_id", "product_category", "id", "categ_id"
        )
        self.assertEqual(alias, "product_template__categ_id")
        alias = query.left_join(
            "product_product", "user_id", "res_user", "id", "user_id"
        )
        self.assertEqual(alias, "product_product__user_id")

        self.assertEqual(
            query.from_clause.code,
            '"product_product" CROSS JOIN "product_template" JOIN "product_category" AS "product_template__categ_id" ON ("product_template"."categ_id" = "product_template__categ_id"."id") LEFT JOIN "res_user" AS "product_product__user_id" ON ("product_product"."user_id" = "product_product__user_id"."id")',
        )
        self.assertEqual(
            query.where_clause.code,
            "product_product.template_id = product_template.id",
        )

    def test_query_chained_explicit_joins(self):
        query = Query(None, "product_product")
        query.add_table("product_template")
        query.add_where(SQL("product_product.template_id = product_template.id"))
        alias = query.join(
            "product_template", "categ_id", "product_category", "id", "categ_id"
        )
        self.assertEqual(alias, "product_template__categ_id")
        alias = query.left_join(
            "product_template__categ_id", "user_id", "res_user", "id", "user_id"
        )
        self.assertEqual(alias, "product_template__categ_id__user_id")

        self.assertEqual(
            query.from_clause.code,
            '"product_product" CROSS JOIN "product_template" JOIN "product_category" AS "product_template__categ_id" ON ("product_template"."categ_id" = "product_template__categ_id"."id") LEFT JOIN "res_user" AS "product_template__categ_id__user_id" ON ("product_template__categ_id"."user_id" = "product_template__categ_id__user_id"."id")',
        )
        self.assertEqual(
            query.where_clause.code,
            "product_product.template_id = product_template.id",
        )

    def test_mixed_query_chained_explicit_implicit_joins(self):
        query = Query(None, "product_product")
        query.add_table("product_template")
        query.add_where(SQL("product_product.template_id = product_template.id"))
        alias = query.join(
            "product_template", "categ_id", "product_category", "id", "categ_id"
        )
        self.assertEqual(alias, "product_template__categ_id")
        alias = query.left_join(
            "product_template__categ_id", "user_id", "res_user", "id", "user_id"
        )
        self.assertEqual(alias, "product_template__categ_id__user_id")
        query.add_table("account_account")
        query.add_where(SQL("product_category.expense_account_id = account_account.id"))

        self.assertEqual(
            query.from_clause.code,
            '"product_product" CROSS JOIN "product_template" CROSS JOIN "account_account" JOIN "product_category" AS "product_template__categ_id" ON ("product_template"."categ_id" = "product_template__categ_id"."id") LEFT JOIN "res_user" AS "product_template__categ_id__user_id" ON ("product_template__categ_id"."user_id" = "product_template__categ_id__user_id"."id")',
        )
        self.assertEqual(
            query.where_clause.code,
            "product_product.template_id = product_template.id AND product_category.expense_account_id = account_account.id",
        )

    def test_raise_missing_lhs(self):
        query = Query(None, "product_product")
        with self.assertRaises(AssertionError):
            query.join(
                "product_template",
                "categ_id",
                "product_category",
                "id",
                "categ_id",
            )

    def test_long_aliases(self):
        query = Query(None, "product_product")
        tmp = query.join(
            "product_product",
            "product_tmpl_id",
            "product_template",
            "id",
            "product_tmpl_id",
        )
        self.assertEqual(tmp, "product_product__product_tmpl_id")
        tmp_cat = query.join(
            tmp,
            "product_category_id",
            "product_category",
            "id",
            "product_category_id",
        )
        self.assertEqual(
            tmp_cat, "product_product__product_tmpl_id__product_category_id"
        )
        tmp_cat_cmp = query.join(
            tmp_cat, "company_id", "res_company", "id", "company_id"
        )
        self.assertEqual(
            tmp_cat_cmp,
            "product_product__product_tmpl_id__product_category_id__9f0ddff7",
        )
        tmp_cat_stm = query.join(
            tmp_cat, "salesteam_id", "res_company", "id", "salesteam_id"
        )
        self.assertEqual(
            tmp_cat_stm,
            "product_product__product_tmpl_id__product_category_id__953a466f",
        )
        tmp_cat_cmp_par = query.join(
            tmp_cat_cmp, "partner_id", "res_partner", "id", "partner_id"
        )
        self.assertEqual(
            tmp_cat_cmp_par,
            "product_product__product_tmpl_id__product_category_id__56d55687",
        )
        tmp_cat_stm_par = query.join(
            tmp_cat_stm, "partner_id", "res_partner", "id", "partner_id"
        )
        self.assertEqual(
            tmp_cat_stm_par,
            "product_product__product_tmpl_id__product_category_id__00363fdd",
        )

    def test_table_expression(self):
        query = Query(None, "foo")
        from_clause = query.from_clause.code
        self.assertEqual(from_clause, '"foo"')

        query = Query(None, "bar", SQL("(SELECT id FROM foo)"))
        from_clause = query.from_clause.code
        self.assertEqual(from_clause, '(SELECT id FROM foo) AS "bar"')

        query = Query(None, "foo")
        query.add_table("bar", SQL("(SELECT id FROM foo)"))
        from_clause = query.from_clause.code
        self.assertEqual(from_clause, '"foo" CROSS JOIN (SELECT id FROM foo) AS "bar"')

        query = Query(None, "foo")
        query.join("foo", "bar_id", SQL("(SELECT id FROM foo)"), "id", "bar")
        from_clause = query.from_clause.code
        self.assertEqual(
            from_clause,
            '"foo" JOIN (SELECT id FROM foo) AS "foo__bar" ON ("foo"."bar_id" = "foo__bar"."id")',
        )

    def test_empty_set_result_ids(self):
        query = Query(None, "foo")
        query.set_result_ids([])
        self.assertEqual(query.get_result_ids(), ())
        self.assertTrue(query.is_empty())
        self.assertIn("SELECT", query.subselect().code, "subselect must contain SELECT")

        query.add_where(SQL("x > 0"))
        self.assertTrue(query.is_empty(), "adding where clauses keeps the result empty")

    def test_set_result_ids(self):
        query = Query(None, "foo")
        query.set_result_ids([1, 2, 3])
        self.assertEqual(query.get_result_ids(), (1, 2, 3))
        self.assertFalse(query.is_empty())

        query.add_where(SQL("x > 0"))
        self.assertIsNone(query._ids, "adding where clause resets the ids")


class TestQuery(TransactionCase):
    def test_auto(self):
        model = self.env["res.partner.category"]
        model.create([{"name": "Test Category 1"}, {"name": "Test Category 2"}])
        query = model._search([])
        self.assertIsInstance(query, Query)

        ids = list(query)
        self.assertGreater(len(ids), 1)

    def test_records_as_query(self):
        records = self.env["res.partner.category"]
        query = records._as_query()
        self.assertEqual(list(query), records.ids)
        self.cr.execute(query.select())
        self.assertEqual([row[0] for row in self.cr.fetchall()], records.ids)

        records = self.env["res.partner.category"].search([])
        query = records._as_query()
        self.assertEqual(list(query), records.ids)
        self.cr.execute(query.select())
        self.assertEqual([row[0] for row in self.cr.fetchall()], records.ids)

        records = records.browse(reversed(records.ids))
        query = records._as_query()
        self.assertEqual(list(query), records.ids)
        self.cr.execute(query.select())
        self.assertEqual([row[0] for row in self.cr.fetchall()], records.ids)

    def test_count_matching_ignores_limit_offset(self):
        model = self.env["res.partner.category"]
        model.create([{"name": f"CM Test {i}"} for i in range(5)])
        query = model._search([("name", "like", "CM Test")], limit=2, offset=1)
        self.assertEqual(len(query), 2)
        self.assertEqual(query.count_matching(), 5)

    def test_count_matching_with_limit(self):
        model = self.env["res.partner.category"]
        model.create([{"name": f"CML Test {i}"} for i in range(5)])
        query = model._search([("name", "like", "CML Test")], limit=2)
        self.assertEqual(query.count_matching(limit=3), 3)
        self.assertEqual(query.count_matching(limit=10), 5)

    def test_count_matching_with_joins(self):
        query = self.env["res.partner"]._search(
            [("is_company", "=", True)], limit=5, order="parent_id"
        )
        total = query.count_matching()
        self.assertGreaterEqual(total, 0)

    def test_extra_tables_and_joins_produce_executable_sql(self):
        """A second table plus a join must reach the server, not just a string.

        `from_clause` used to separate tables with a comma, which binds looser
        than an explicit JOIN, so an ON clause naming anything but the table
        immediately to its left was rejected:
            ERROR:  invalid reference to FROM-clause entry for table "res_partner"
        Two of the string assertions in QueryTestCase pinned exactly that SQL,
        and none of them executed it -- which is why the shape survived. This
        one executes.
        """
        query = Query(self.env, "res_partner")
        query.add_table("res_users")
        query.left_join("res_partner", "company_id", "res_company", "id", "company")
        query.add_where(SQL('"res_users"."partner_id" = "res_partner"."id"'))
        query.limit = 1
        # the assertion is that this does not raise
        self.env.execute_query(query.select())

    def test_count_matching_honours_a_zero_limit(self):
        """limit=0 is a limit, and its answer is 0.

        `if limit:` sent a zero down the unlimited branch and returned the full
        count -- while search_count(domain, limit=0) reaches Query.__len__,
        which has read it as `is not None` since the limit-zero pass. The two
        counters on one class disagreed about one input.
        """
        model = self.env["res.partner.category"]
        model.create([{"name": f"CMZ Test {i}"} for i in range(3)])
        query = model._search([("name", "like", "CMZ Test")])
        self.assertEqual(query.count_matching(limit=0), 0)
        self.assertEqual(query.count_matching(limit=2), 2)
        self.assertEqual(query.count_matching(), 3)
        self.assertEqual(model.search_count([("name", "like", "CMZ Test")], limit=0), 0)

    def test_a_widening_limit_drops_the_memoised_empty_result(self):
        """limit and offset can turn an empty result non-empty.

        `_invalidate_ids` keeps a memoised () on purpose, and its comment used
        to argue no mutator could repopulate. Two can: raising `limit` off 0 and
        lowering `offset` past the end. Both returned the stale () from
        get_result_ids/__bool__/__len__/__iter__ with no query issued.
        """
        model = self.env["res.partner.category"]
        model.create([{"name": f"CMW Test {i}"} for i in range(3)])
        domain = [("name", "like", "CMW Test")]

        query = model._search(domain)
        query.limit = 0
        self.assertEqual(query.get_result_ids(), ())
        query.limit = 10
        self.assertEqual(len(query.get_result_ids()), 3)
        self.assertFalse(query.is_empty())

        query = model._search(domain)
        query.offset = 99
        self.assertEqual(query.get_result_ids(), ())
        query.offset = 0
        self.assertEqual(len(query.get_result_ids()), 3)
        self.assertTrue(bool(query))
