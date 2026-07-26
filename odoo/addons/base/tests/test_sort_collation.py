"""``sorted()`` orders text by code point; ``search(order=...)`` by DB collation.

Code routinely assumes the two agree, and they do -- but only because Odoo
creates every database with ``LC_COLLATE 'C'``
(``service/db.py::_create_empty_database``), where byte order and code-point
order coincide.  That is a load-bearing platform invariant, not a coincidence:
lose it and every in-memory re-sort silently stops reproducing the order the
records were searched in.

These tests pin both halves independently -- the in-memory order is code-point
order whatever the database does, the SQL order follows the database -- so the
day they stop agreeing, the reason is visible here.  ``_create_empty_database``
warns when a configured ``db_template`` would break the invariant.
"""

from odoo.tests.common import TransactionCase

NAMES = ["apple", "Apple", "ápple", "banana", "Banana", "Ärger", "zebra", "Zebra"]


class TestSortCollation(TransactionCase):
    """Pin the in-memory / SQL ordering divergence."""

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
        """``sorted()`` must order by Python comparison, whatever the collation."""
        self.partners.fetch(["name"])
        got = self.partners.sorted("name").mapped("name")
        self.assertEqual(got, sorted(NAMES))

    def test_fast_path_matches_the_record_based_sort(self):
        """The raw-cache fast path must reproduce the record-based sort exactly."""
        self.partners.fetch(["name"])
        for order in ("name", "name DESC", "name ASC NULLS LAST"):
            with self.subTest(order=order):
                fast = self.partners._sorted_by_ids(order, False)
                self.assertIsNotNone(fast, "fast path unexpectedly bailed out")
                key = self.partners._sorted_order_to_function(order)
                slow = tuple(r.id for r in sorted(self.partners, key=key))
                self.assertEqual(fast, slow)

    def test_sql_order_follows_the_database_collation(self):
        """``search(order=...)`` must follow the database, not Python."""
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
