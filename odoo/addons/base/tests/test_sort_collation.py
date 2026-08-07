from odoo.tests.common import TransactionCase

NAMES = ["apple", "Apple", "ápple", "banana", "Banana", "Ärger", "zebra", "Zebra"]


class TestSortCollation(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.partners = cls.env["res.partner"].create([{"name": n} for n in NAMES])
        cls.env.flush_all()

    def _db_collation(self):
        self.env.cr.execute(
            "SELECT datcollate FROM pg_database WHERE datname = current_database()"
        )
        return self.env.cr.fetchone()[0]

    def test_in_memory_sort_is_code_point_order(self):
        self.partners.fetch(["name"])
        got = self.partners.sorted("name").mapped("name")
        self.assertEqual(got, sorted(NAMES))

    def test_fast_path_matches_the_record_based_sort(self):
        self.partners.fetch(["name"])
        for order in ("name", "name DESC", "name ASC NULLS LAST"):
            with self.subTest(order=order):
                fast = self.partners._sorted_by_ids(order, False)
                self.assertIsNotNone(fast, "fast path unexpectedly bailed out")
                key = self.partners._sorted_order_to_function(order)
                slow = tuple(r.id for r in sorted(self.partners, key=key))
                self.assertEqual(fast, slow)

    def test_sql_order_follows_the_database_collation(self):
        model = self.env["res.partner"].with_context(active_test=False)
        searched = model.search([("id", "in", self.partners.ids)], order="name")
        self.env.cr.execute(
            "SELECT id FROM res_partner WHERE id = ANY(%s) ORDER BY name",
            (self.partners.ids,),
        )
        self.assertEqual(searched.ids, [row[0] for row in self.env.cr.fetchall()])

        if self._db_collation() == "C":
            self.assertEqual(
                searched.ids,
                self.partners.sorted("name").ids,
                "under LC_COLLATE=C the two orders must agree -- the invariant "
                "every in-memory re-sort depends on",
            )
            return
        self.assertNotEqual(
            searched.ids,
            self.partners.sorted("name").ids,
            "collation-aware SQL order unexpectedly matched the code-point sort",
        )
