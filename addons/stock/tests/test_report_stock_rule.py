from odoo.fields import Command
from odoo.tests import TransactionCase, tagged


@tagged("post_install", "-at_install")
class TestReportStockRule(TransactionCase):
    """Data-layer tests for the ``report.stock.report_stock_rule`` 2D report."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.report = cls.env["report.stock.report_stock_rule"]
        cls.warehouse = cls.env["stock.warehouse"].create(
            {"name": "RSR Test WH", "code": "RSRT"}
        )
        cls.stock = cls.warehouse.lot_stock_id
        cls.supplier = cls.env.ref("stock.stock_location_suppliers")
        cls.customer = cls.env.ref("stock.stock_location_customers")

        # A minimal route: supplier -> stock -> customer, two push rules so the
        # destination is location_dest_id (deterministic, no picking-type detour).
        cls.route = cls.env["stock.route"].create({"name": "RSR Route"})
        cls.rule_in = cls.env["stock.rule"].create(
            {
                "name": "RSR in",
                "route_id": cls.route.id,
                "action": "push",
                "location_src_id": cls.supplier.id,
                "location_dest_id": cls.stock.id,
                "picking_type_id": cls.warehouse.in_type_id.id,
            }
        )
        cls.rule_out = cls.env["stock.rule"].create(
            {
                "name": "RSR out",
                "route_id": cls.route.id,
                "action": "push",
                "location_src_id": cls.stock.id,
                "location_dest_id": cls.customer.id,
                "picking_type_id": cls.warehouse.out_type_id.id,
            }
        )
        cls.product = cls.env["product.product"].create(
            {
                "name": "RSR Product",
                "is_storable": True,
                "route_ids": [Command.link(cls.route.id)],
            }
        )

    def _report_values(self):
        data = {"product_id": self.product.id, "warehouse_ids": self.warehouse.ids}
        return self.report._get_report_values(None, data=data)

    # -- ordering ----------------------------------------------------------
    def test_locations_follow_the_flow(self):
        """Supplier is leftmost, customer rightmost, stock in between."""
        vals = self._report_values()
        order = list(vals["locations"])
        self.assertLess(order.index(self.supplier), order.index(self.stock))
        self.assertLess(order.index(self.stock), order.index(self.customer))

    def test_topological_rank_is_cycle_safe(self):
        """A cycle must not hang or drop nodes; every location gets a rank."""
        a, b, c = (
            self.env["stock.location"].create({"name": n, "usage": "internal"})
            for n in ("A", "B", "C")
        )
        edges = [(a, b), (b, c), (c, a)]  # 3-cycle
        rank = self.report._topological_rank(a | b | c, edges)
        self.assertEqual(sorted(rank), sorted((a | b | c).ids))
        self.assertEqual(len(set(rank.values())), 3)

    # -- route lines / positioning ----------------------------------------
    def test_route_lines_positions_and_dense_colors(self):
        vals = self._report_values()
        loc_index = {loc.id: i for i, loc in enumerate(vals["locations"])}
        rows = vals["route_lines"]
        # every row spans exactly one slot per location column
        for row in rows:
            self.assertEqual(len(row), len(vals["locations"]))

        # colors are dense: the drawn routes use a contiguous palette prefix,
        # never skipping a color for a route that had nothing to display.
        palette = self.report._get_route_colors()
        used = []
        for row in rows:
            for slot in row:
                if slot and slot[2] not in used:
                    used.append(slot[2])
        self.assertEqual(used, palette[: len(used)])

        # our own rule renders origin@supplier, destination@stock
        row_in = next(r for r in rows if any(s and s[0] == self.rule_in for s in r))
        self.assertEqual(row_in[loc_index[self.supplier.id]][1], "origin")
        self.assertEqual(row_in[loc_index[self.stock.id]][1], "destination")
        # and the two grid cells belong to the same (single) route color
        rule_colors = {s[2] for s in row_in if s}
        self.assertEqual(len(rule_colors), 1)

    def test_positions_use_id_not_display_name(self):
        """Two locations sharing a display_name must not collapse to one column.

        Regression guard: the report must index columns by location id, never by
        the (non-unique) display_name.
        """
        dup1, dup2 = (
            self.env["stock.location"].create({"name": "DUP", "usage": "internal"})
            for _ in range(2)
        )
        self.assertEqual(dup1.display_name, dup2.display_name)
        rule = self.env["stock.rule"].create(
            {
                "name": "RSR dup",
                "route_id": self.route.id,
                "action": "push",
                "location_src_id": dup1.id,
                "location_dest_id": dup2.id,
                "picking_type_id": self.warehouse.int_type_id.id,
            }
        )
        loc_by_rule = {rule: self.report._get_rule_loc(rule, self.product)}
        locations = dup1 | dup2
        rows = self.report._get_route_lines(rule.route_id, rule, loc_by_rule, locations)
        self.assertEqual(len(rows), 1)
        row = rows[0]
        self.assertEqual(row[0][1], "origin")  # dup1 column
        self.assertEqual(row[1][1], "destination")  # dup2 column, distinct

    # -- header lines ------------------------------------------------------
    def test_header_lines_are_recordsets(self):
        self.env["stock.warehouse.orderpoint"].create(
            {
                "product_id": self.product.id,
                "location_id": self.stock.id,
                "product_min_qty": 1,
                "product_max_qty": 5,
            }
        )
        zone = self.env["stock.location"].create(
            {"name": "ZONE", "location_id": self.stock.id, "usage": "internal"}
        )
        self.env["stock.putaway.rule"].create(
            {
                "product_id": self.product.id,
                "location_in_id": self.stock.id,
                "location_out_id": zone.id,
            }
        )
        vals = self._report_values()
        header = vals["header_lines"][self.stock.id]
        self.assertEqual(header["orderpoint"]._name, "stock.warehouse.orderpoint")
        self.assertEqual(header["putaway"]._name, "stock.putaway.rule")
        self.assertEqual(len(header["orderpoint"]), 1)
        self.assertEqual(len(header["putaway"]), 1)
