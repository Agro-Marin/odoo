import logging
from collections import defaultdict
from functools import partial

from odoo import api, models
from odoo.fields import Domain

_logger = logging.getLogger(__name__)


class StockRuleSelection(models.Model):
    _inherit = "stock.rule"

    def _get_route_buckets(self, route_ids, packaging_uom_id, product_id, warehouse_id):
        if route_ids:
            yield route_ids
        if packaging_uom_id:
            yield packaging_uom_id.package_type_id.route_ids
        yield product_id.route_ids | product_id.categ_id.total_route_ids
        if warehouse_id:
            yield warehouse_id.route_ids

    @api.model
    def _get_valid_route_ids(
        self, route_ids, packaging_uom_id, product_id, warehouse_ids
    ):
        valid_route_ids = set()
        no_warehouse = self.env["stock.warehouse"]
        for routes in self._get_route_buckets(
            route_ids, packaging_uom_id, product_id, no_warehouse
        ):
            valid_route_ids |= set(routes.ids)
        if warehouse_ids:
            valid_route_ids |= set(
                warehouse_ids.route_ids.filtered(
                    partial(self._is_route_usable_for, product_id),
                ).ids,
            )
        return valid_route_ids

    @api.model
    def _get_rule_candidates(self, values, locations, warehouse_ids, valid_route_ids):
        domain = self._get_rule_location_domain(
            locations,
        ) & self._get_rule_scope_domain(values)
        if warehouse_ids:
            domain &= Domain("warehouse_id", "in", [False, *warehouse_ids.ids])
        if valid_route_ids:
            domain &= Domain("route_id", "in", list(valid_route_ids))
        candidates = defaultdict(lambda: defaultdict(lambda: self.env["stock.rule"]))
        for location, route, rules in self.env["stock.rule"]._read_group(
            domain,
            groupby=["location_dest_id", "route_id"],
            aggregates=["id:recordset"],
        ):
            candidates[location.id][route.id] |= rules
        return candidates

    def _is_route_usable_for(self, product, route):
        return True

    @api.model
    def _sorted_by_precedence(self, rules, warehouse_id):
        return rules.sorted(
            key=lambda rule: (
                bool(warehouse_id) and rule.warehouse_id != warehouse_id,
                rule.route_sequence,
                rule.sequence,
                rule.id,
            ),
        )

    @api.model
    def _sorted_bucket_routes(self, routes, product_id):
        product_route_ids = set(product_id.route_ids.ids)
        return routes.sorted(
            key=lambda route: (
                route.id not in product_route_ids,
                route.sequence,
                route.id,
            ),
        )

    @api.model
    def _get_sorted_buckets(self, product_id, warehouse_id, values):
        return [
            self._sorted_bucket_routes(routes, product_id)
            for routes in self._get_route_buckets(
                values.get("route_ids") or self.env["stock.route"],
                values.get("packaging_uom_id") or self.env["uom.uom"],
                product_id,
                warehouse_id,
            )
        ]

    @api.model
    def _get_best_rule(self, candidates_by_route, sorted_buckets, warehouse_id):
        for routes in sorted_buckets:
            for route in routes:
                candidates = candidates_by_route.get(route.id)
                if not candidates:
                    continue
                if warehouse_id:
                    candidates = candidates.filtered(
                        lambda rule: (
                            not rule.warehouse_id or rule.warehouse_id == warehouse_id
                        ),
                    )
                if candidates:
                    return self._sorted_by_precedence(candidates, warehouse_id)[:1]
        return self.env["stock.rule"]

    def _get_rule_by_domain(
        self, route_ids, packaging_uom_id, product_id, warehouse_id, domain
    ):
        values = {"route_ids": route_ids, "packaging_uom_id": packaging_uom_id}
        domain = Domain(domain)
        if warehouse_id:
            domain &= Domain("warehouse_id", "in", [False, warehouse_id.id])
        valid_route_ids = self._get_valid_route_ids(
            route_ids, packaging_uom_id, product_id, warehouse_id
        )
        if valid_route_ids:
            domain &= Domain("route_id", "in", list(valid_route_ids))
        candidates_by_route = defaultdict(lambda: self.env["stock.rule"])
        for route, rules in self.env["stock.rule"]._read_group(
            domain, groupby=["route_id"], aggregates=["id:recordset"]
        ):
            candidates_by_route[route.id] |= rules
        return self._get_best_rule(
            candidates_by_route,
            self._get_sorted_buckets(product_id, warehouse_id, values),
            warehouse_id,
        )

    @api.model
    def _get_location_hierarchy(self, location_id):
        locations = location_id
        while locations[-1].location_id:
            locations |= locations[-1].location_id
        return locations

    @api.model
    def _get_rule_from_hierarchy(self, candidates, product_id, locations, values):
        intercomp_transit = self._get_intercomp_transit_location()
        intercomp_customers = self.env["stock.location"]
        if self._check_intercomp_location(locations):
            intercomp_customers = self.env.ref(
                "stock.stock_location_customers", raise_if_not_found=False
            )
        buckets_by_warehouse = {}
        for location in locations:
            candidate_locations = location
            if intercomp_customers and location == intercomp_transit:
                candidate_locations = location | intercomp_customers
            for candidate_location in candidate_locations:
                warehouse_id = values.get(
                    "warehouse_id",
                    candidate_location.warehouse_id,
                )
                if warehouse_id.id not in buckets_by_warehouse:
                    buckets_by_warehouse[warehouse_id.id] = self._get_sorted_buckets(
                        product_id, warehouse_id, values
                    )
                rule = self._get_best_rule(
                    candidates.get(candidate_location.id) or {},
                    buckets_by_warehouse[warehouse_id.id],
                    warehouse_id,
                )
                if rule:
                    return rule
        return self.env["stock.rule"]

    @api.model
    def _get_rule(self, product_id, location_id, values):
        Rule = self.env["stock.rule"]
        if not location_id:
            return Rule
        locations = self._get_location_hierarchy(location_id)
        warehouse_ids = values.get("warehouse_id", locations.warehouse_id)
        candidates = self._get_rule_candidates(
            values,
            locations,
            warehouse_ids,
            self._get_valid_route_ids(
                values.get("route_ids", False),
                values.get("packaging_uom_id", False),
                product_id,
                warehouse_ids,
            ),
        )
        return self._get_rule_from_hierarchy(candidates, product_id, locations, values)

    @api.model
    def _get_rules_batch(self, procurements):
        Rule = self.env["stock.rule"]
        rules = [Rule] * len(procurements)
        groups = defaultdict(list)
        for index, procurement in enumerate(procurements):
            if not procurement.location_id:
                continue
            values = procurement.values
            locations = self._get_location_hierarchy(procurement.location_id)
            warehouse_ids = values.get("warehouse_id", locations.warehouse_id)
            valid_route_ids = self._get_valid_route_ids(
                values.get("route_ids", False),
                values.get("packaging_uom_id", False),
                procurement.product_id,
                warehouse_ids,
            )
            key = (
                str(self._get_rule_scope_domain(values)),
                locations[-1].id,
                tuple(warehouse_ids.ids),
                frozenset(valid_route_ids),
            )
            groups[key].append((index, procurement, locations, valid_route_ids))
        for group in groups.values():
            group_locations = self.env["stock.location"].union(
                *(locations for _index, _procurement, locations, _routes in group),
            )
            _index0, representative, _locations0, valid_route_ids = group[0]
            warehouse_ids = representative.values.get(
                "warehouse_id",
                group[0][2].warehouse_id,
            )
            candidates = self._get_rule_candidates(
                representative.values,
                group_locations,
                warehouse_ids,
                valid_route_ids,
            )
            for index, procurement, locations, _routes in group:
                rules[index] = self._get_rule_from_hierarchy(
                    candidates, procurement.product_id, locations, procurement.values
                )
        return rules

    @api.model
    def _get_intercomp_transit_location(self):
        return (
            self.env.ref(
                "stock.stock_location_inter_company",
                raise_if_not_found=False,
            )
            or self.env["stock.location"]
        )

    @api.model
    def _check_intercomp_location(self, locations):
        if not locations.filtered(lambda location: location.usage == "transit"):
            return False
        return self._get_intercomp_transit_location().id in locations.ids

    @api.model
    def _get_rule_domain(self, locations, values):
        return self._get_rule_location_domain(
            locations,
        ) & self._get_rule_scope_domain(values)

    @api.model
    def _get_rule_location_domain(self, locations):
        location_ids = locations.ids
        if self._check_intercomp_location(locations):
            customers_location = self.env.ref(
                "stock.stock_location_customers", raise_if_not_found=False
            )
            if customers_location:
                location_ids.append(customers_location.id)
        return Domain("location_dest_id", "in", location_ids) & Domain(
            "action", "!=", "push"
        )

    @api.model
    def _get_rule_scope_domain(self, values):
        domain = Domain.TRUE
        if self.env.su and values.get("company_id"):
            company_ids = set(values["company_id"].ids)
            if values.get("route_ids"):
                company_ids |= set(values["route_ids"].company_id.ids)
            domain &= Domain(
                [
                    "|",
                    ("company_id", "=", False),
                    ("company_id", "child_of", list(company_ids)),
                ],
            )
        return domain

    @api.model
    def _get_push_rule(self, product_id, location_dest_id, values):
        found_rule = self.env["stock.rule"]
        location = location_dest_id
        while (not found_rule) and location:
            domain = Domain("location_src_id", "=", location.id) & Domain(
                "action", "in", ("push", "pull_push")
            )
            if dom := values.get("domain"):
                domain &= Domain(dom)
            found_rule = self._get_rule_by_domain(
                values.get("route_ids"),
                values.get("packaging_uom_id"),
                product_id,
                values.get("warehouse_id"),
                domain,
            )
            location = location.location_id
        return found_rule
