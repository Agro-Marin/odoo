"""Schema guards for the columns the ORM walks on its own."""

import re

from odoo.tests import tagged
from odoo.tests.common import TransactionCase


@tagged("post_install", "-at_install")
class TestMrpSchema(TransactionCase):
    """Every Many2one that a `related` field traverses must carry an index.

    A non-stored `related` is not read record by record: `_traverse_related_sql`
    (odoo/orm/models/mixins/_query.py) compiles it to a `LEFT JOIN` on the
    comodel, and `Many2one.join` (odoo/orm/fields/relational/many2one.py) emits
    that join on the Many2one column itself.

    Our own index lint only demands an index on the inverse of a One2many, which
    is why these three were left without one while `date_start`,
    `production_group_id` and `picking_type_id` already carry theirs.
    """

    # (table, column) -> what traverses it, quoted in the failure message.
    TRAVERSED = {
        ("mrp_production", "product_id"): (
            "three related fields on mrp.production (product_variant_attributes, "
            "product_tracking, product_tmpl_id) and the two-hop chain through "
            "mrp.workorder.product_id, itself related to production_id.product_id"
        ),
        ("mrp_production", "location_src_id"): (
            "mrp.production.warehouse_id, read by the BoM overview, the MO "
            "overview and every component default"
        ),
        ("mrp_production", "bom_id"): ("mrp.workorder.production_bom_id"),
    }

    def _index_definitions(self, table):
        self.env.cr.execute(
            """
            SELECT indexdef
              FROM pg_indexes
             WHERE schemaname = current_schema()
               AND tablename = %s
            """,
            [table],
        )
        return [indexdef for [indexdef] in self.env.cr.fetchall()]

    def test_related_many2one_columns_are_indexed(self):
        for (table, column), traversed_by in self.TRAVERSED.items():
            with self.subTest(table=table, column=column):
                definitions = self._index_definitions(table)
                # Pin the exact single-column list. A loose `%product_id%` would
                # also match a composite index that leads with another column,
                # which Postgres cannot use for this join.
                self.assertTrue(
                    any(
                        re.search(rf"USING btree \({column}\)", indexdef)
                        for indexdef in definitions
                    ),
                    f"{table}.{column} must carry a btree index: it is "
                    f"traversed by {traversed_by}.",
                )
