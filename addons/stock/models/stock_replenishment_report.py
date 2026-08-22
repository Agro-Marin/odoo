from collections import defaultdict

from dateutil import relativedelta

from odoo import SUPERUSER_ID, _, api, fields, models
from odoo.fields import Domain
from odoo.tools import float_compare


class StockReplenishmentReport(models.AbstractModel):
    _name = "stock.replenishment.report"
    _description = "Replenishment Shortage Scan"

    @api.model
    def _create_missing_orderpoints(self, orderpoints):
        shortages = self._get_projected_shortages()
        shortages = self._net_shortages(shortages, orderpoints)
        return self._create_shortage_orderpoints(shortages, orderpoints)

    @api.model
    def _get_candidate_products(self):
        return self.env["product.product"].search(
            [("is_storable", "=", True), ("stock_move_ids", "!=", False)],
        )

    @api.model
    def _get_replenish_locations(self):
        return self.env["stock.location"].search([("replenish_location", "=", True)])

    @api.model
    def _get_uncovered_quantities(self, products, locations):
        Move = self.env["stock.move"].with_context(active_test=False)
        Quant = self.env["stock.quant"].with_context(active_test=False)
        Location = self.env["stock.location"]
        domain_quant, _dummy, domain_move_out_loc = Location._quantity_domains(
            locations.ids,
        )
        domain_state = Domain(
            "state",
            "in",
            ("waiting", "confirmed", "assigned", "partially_available"),
        )
        domain_product = Domain("product_id", "in", products.ids)
        domain_quant = Domain.AND((domain_product, domain_quant))
        domain_move_out = Domain.AND(
            (domain_product, domain_state, domain_move_out_loc),
        )

        replenish_ids = set(locations.ids)
        ancestors_by_location = {}

        def replenish_ancestors(location):
            if not location:
                return ()
            ancestors = ancestors_by_location.get(location.id)
            if ancestors is None:
                ancestors = tuple(
                    ancestor_id
                    for ancestor_id in map(
                        int,
                        (location.parent_path or "").split("/")[:-1],
                    )
                    if ancestor_id in replenish_ids
                )
                ancestors_by_location[location.id] = ancestors
            return ancestors

        net_qty = defaultdict(float)
        for product, location, qty in Move._read_group(
            domain_move_out,
            ["product_id", "location_id"],
            ["product_qty:sum"],
        ):
            for replenish_id in replenish_ancestors(location):
                net_qty[product, replenish_id] -= qty
        for product, location, qty in Quant._read_group(
            domain_quant,
            ["product_id", "location_id"],
            ["quantity:sum"],
        ):
            for replenish_id in replenish_ancestors(location):
                net_qty[product, replenish_id] += qty
        return net_qty

    @api.model
    def _get_projected_shortages(self):
        products = self._get_candidate_products()
        locations = self._get_replenish_locations()
        uncovered = self._get_uncovered_quantities(products, locations)

        location_by_id = {location.id: location for location in locations}
        Orderpoint = self.env["stock.warehouse.orderpoint"]
        extra_routes = products._get_total_routes_by_product()
        rules_cache = {}
        products_by_horizon = defaultdict(set)
        for (product, location_id), quantity in uncovered.items():
            if product.uom_id.compare(quantity, 0) >= 0:
                continue
            location = location_by_id[location_id]
            cache_key = (
                location,
                product.route_ids,
                product.route_ids
                | product.categ_id.total_route_ids
                | extra_routes[product.id],
            )
            rules = rules_cache.get(cache_key)
            if rules is None:
                rules = product._get_rules_from_location(location)
                rules_cache[cache_key] = rules
            lead_days = rules.with_context(
                bypass_delay_description=True,
                global_horizon_days=Orderpoint._get_horizon_days(location.company_id),
            )._get_lead_days(product)[0]
            horizon = lead_days["total_delay"] + lead_days["horizon_time"]
            products_by_horizon[horizon, location].add(product.id)

        end_of_today = fields.Datetime.now().replace(hour=23, minute=59, second=59)
        shortages = {}
        for (horizon, location), product_ids in products_by_horizon.items():
            candidates = self.env["product.product"].browse(product_ids)
            forecasts = candidates.with_context(
                location=location.id,
                to_date=end_of_today + relativedelta.relativedelta(days=horizon),
            ).read(["qty_available_virtual"])
            products_by_id = {product.id: product for product in candidates}
            for forecast in forecasts:
                product = products_by_id[forecast["id"]]
                quantity = forecast["qty_available_virtual"]
                if product.uom_id.compare(quantity, 0) < 0:
                    shortages[product.id, location.id] = quantity
        return shortages

    @api.model
    def _net_shortages(self, shortages, orderpoints):
        if not shortages:
            return shortages
        Orderpoint = self.env["stock.warehouse.orderpoint"]
        product_ids = list({product_id for product_id, _location in shortages})
        location_ids = list({location_id for _product, location_id in shortages})
        in_progress = (
            self.env["product.product"]
            .browse(product_ids)
            ._get_quantity_in_progress(location_ids=location_ids)[0]
        )
        suggested = {
            (product.id, location.id): sum(group.mapped("qty_to_order"))
            for product, location, group in Orderpoint._read_group(
                [("id", "in", orderpoints.ids), ("product_id", "in", product_ids)],
                ["product_id", "location_id"],
                ["id:recordset"],
            )
        }
        precision_digits = self.env["decimal.precision"].precision_get("Product Unit")
        netted = {}
        for key, quantity in shortages.items():
            covered = (in_progress.get(key) or 0.0) + suggested.get(key, 0.0)
            remaining = quantity + covered
            if float_compare(remaining, 0.0, precision_digits=precision_digits) < 0:
                netted[key] = remaining
        return netted

    @api.model
    def _create_shortage_orderpoints(self, shortages, orderpoints):
        Orderpoint = self.env["stock.warehouse.orderpoint"]
        if not shortages:
            return Orderpoint.browse()
        existing = {
            (product.id, location.id)
            for product, location, _group in Orderpoint.with_context(
                active_test=False,
            )._read_group(
                [
                    ("id", "in", orderpoints.ids),
                    (
                        "product_id",
                        "in",
                        list({product_id for product_id, _loc in shortages}),
                    ),
                ],
                ["product_id", "location_id"],
                ["id:recordset"],
            )
        }
        values_list = []
        for product_id, location_id in shortages:
            if (product_id, location_id) in existing:
                continue
            location = self.env["stock.location"].browse(location_id)
            values = Orderpoint._get_orderpoint_values(product_id, location_id)
            values.update(
                {
                    "name": _("Replenishment Report"),
                    "warehouse_id": location.warehouse_id.id
                    or self.env["stock.warehouse"]
                    .search([("company_id", "=", location.company_id.id)], limit=1)
                    .id,
                    "company_id": location.company_id.id,
                },
            )
            values_list.append(values)
        return Orderpoint.with_user(SUPERUSER_ID).create(values_list)
