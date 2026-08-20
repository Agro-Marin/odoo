"""Pins for the drop-shipping exclusion in `mixin.stock.replenish`."""

from odoo.tests import TransactionCase, tagged


@tagged("post_install", "-at_install")
class TestReplenishRouteDomain(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.warehouse = cls.env["stock.warehouse"].search(
            [("company_id", "=", cls.env.company.id)], limit=1
        )
        cls.product = cls.env["product.product"].create(
            {"name": "Replenished", "type": "consu", "is_storable": True}
        )
        cls.route = cls.env.ref("stock_dropshipping.route_drop_shipping")
        # The base domain only keeps routes with a rule landing inside a warehouse.
        # Without one, the exclusion under test is unobservable.
        cls.env["stock.rule"].create(
            {
                "name": "Dropship into the warehouse",
                "route_id": cls.route.id,
                "action": "pull",
                "picking_type_id": cls.warehouse.in_type_id.id,
                "location_src_id": cls.env.ref("stock.stock_location_suppliers").id,
                "location_dest_id": cls.warehouse.lot_stock_id.id,
                "company_id": cls.warehouse.company_id.id,
            }
        )

    def _wizard(self):
        return self.env["product.replenish"].new(
            {
                "product_id": self.product.id,
                "product_tmpl_id": self.product.product_tmpl_id.id,
                "product_uom_id": self.product.uom_id.id,
                "quantity": 1,
                "warehouse_id": self.warehouse.id,
            }
        )

    def test_drop_shipping_is_excluded(self):
        allowed = self.env["stock.route"].search(
            self._wizard()._get_allowed_route_domain()
        )
        self.assertNotIn(self.route, allowed)

    def test_excluded_exactly_once(self):
        """`mrp_subcontracting_dropshipping` re-declared this module's override
        verbatim while depending on it, so the same leaf was added twice."""
        domain = repr(self._wizard()._get_allowed_route_domain())
        self.assertEqual(domain.count(f"'id', '!=', {self.route.id}"), 1)

    def test_a_deleted_route_does_not_break_the_wizard(self):
        """`env.ref(..., raise_if_not_found=False)` answers None, and nothing refuses
        the route's deletion -- reading `.id` off it made Replenish unusable."""
        self.route.unlink()
        self.env.transaction._ref_cache.clear()
        self.env.invalidate_all()

        allowed = self.env["stock.route"].search(
            self._wizard()._get_allowed_route_domain()
        )
        self.assertNotIn(self.route, allowed)
