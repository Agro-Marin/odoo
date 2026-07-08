from collections import defaultdict

from odoo import api, models

# Palette cycled through, one color per drawn route. Kept as a hook (see
# ``_get_route_colors``) so downstream modules can override it.
ROUTE_COLORS = (
    "#FFA500",
    "#800080",
    "#228B22",
    "#008B8B",
    "#4682B4",
    "#FF0000",
    "#32CD32",
)


class ReportStockReport_Stock_Rule(models.AbstractModel):
    _name = "report.stock.report_stock_rule"
    _description = "Stock rule report"

    @api.model
    def _get_report_values(self, docids, data=None):
        data = data or {}
        product = self.env["product.product"].browse(data.get("product_id", docids))
        product.ensure_one()
        warehouses = self.env["stock.warehouse"].browse(data.get("warehouse_ids") or [])
        # Re-expose normalized ids: ``_get_routes`` (and downstream overrides such
        # as sale_stock's) read the product/warehouses back out of ``data``.
        data = {**data, "product_id": product.id, "warehouse_ids": warehouses.ids}

        routes = self._get_routes(data)

        # Some routes carry rules of several warehouses; only keep the rules with
        # no warehouse or belonging to a selected one. For each we resolve its
        # source and destination location.
        relevant_rules = routes.rule_ids.filtered(
            lambda r: not r.warehouse_id or r.warehouse_id in warehouses
        )
        rules_and_loc = [self._get_rule_loc(rule, product) for rule in relevant_rules]
        loc_by_rule = {rl["rule"]: rl for rl in rules_and_loc}

        locations = self._sort_locations(rules_and_loc, warehouses)
        reordering_rules = self.env["stock.warehouse.orderpoint"].search(
            [("product_id", "=", product.id)]
        )
        locations |= reordering_rules.location_id

        header_lines = self._get_header_lines(
            locations, product.putaway_rule_ids, reordering_rules
        )
        route_lines = self._get_route_lines(
            routes, relevant_rules, loc_by_rule, locations
        )
        return {
            "docs": product,
            "locations": locations,
            "header_lines": header_lines,
            "route_lines": route_lines,
            "is_rtl": self.env["res.lang"]._lang_get(self.env.user.lang).direction
            == "rtl",
        }

    @api.model
    def _get_header_lines(self, locations, putaway_rules, reordering_rules):
        """Map each location to the putaway/reordering rules it hosts.

        Returns ``{location_id: {"putaway": recordset, "orderpoint": recordset}}``,
        only for locations that host at least one of either.
        """
        putaways_by_loc = defaultdict(lambda: self.env["stock.putaway.rule"])
        for putaway in putaway_rules:
            putaways_by_loc[putaway.location_in_id.id] |= putaway
        orderpoints_by_loc = defaultdict(lambda: self.env["stock.warehouse.orderpoint"])
        for orderpoint in reordering_rules:
            orderpoints_by_loc[orderpoint.location_id.id] |= orderpoint

        header_lines = {}
        for location in locations:
            putaways = putaways_by_loc.get(location.id)
            orderpoints = orderpoints_by_loc.get(location.id)
            if putaways or orderpoints:
                header_lines[location.id] = {
                    "putaway": putaways or self.env["stock.putaway.rule"],
                    "orderpoint": orderpoints or self.env["stock.warehouse.orderpoint"],
                }
        return header_lines

    @api.model
    def _get_route_lines(self, routes, relevant_rules, loc_by_rule, locations):
        """Build one grid row per displayed rule.

        Each row has a slot per location (same order/length as ``locations``);
        a slot is an empty list for locations the rule doesn't touch, or a
        ``(rule, "origin"|"destination", color)`` tuple for its source/dest.
        Locations are addressed by id, never by ``display_name`` (which is not
        unique). One palette color is consumed per route that is actually drawn.
        """
        loc_index = {location.id: idx for idx, location in enumerate(locations)}
        colors = self._get_route_colors()
        route_lines = []
        color_index = 0
        for route in routes:
            rules_to_display = route.rule_ids & relevant_rules
            if not rules_to_display:
                continue
            route_color = colors[color_index % len(colors)]
            color_index += 1
            for rule in rules_to_display:
                rule_loc = loc_by_rule[rule]
                row = [[] for _ in locations]
                # Destination first, then source: a rule whose source and
                # destination collapse to one location renders as "origin".
                destination = rule_loc["destination"]
                source = rule_loc["source"]
                if destination.id in loc_index:
                    row[loc_index[destination.id]] = (rule, "destination", route_color)
                if source.id in loc_index:
                    row[loc_index[source.id]] = (rule, "origin", route_color)
                route_lines.append(row)
        return route_lines

    @api.model
    def _get_route_colors(self):
        return list(ROUTE_COLORS)

    @api.model
    def _get_routes(self, data):
        """Extract the routes to display from the wizard's content."""
        product = self.env["product.product"].browse(data["product_id"])
        warehouses = self.env["stock.warehouse"].browse(data["warehouse_ids"])
        return (
            product.route_ids | product.categ_id.total_route_ids | warehouses.route_ids
        )

    @api.model
    def _get_rule_loc(self, rule, product):
        rule.ensure_one()
        destination = (
            rule.location_dest_id
            if rule.action != "pull"
            else rule.picking_type_id.default_location_dest_id
        )
        return {
            "rule": rule,
            "source": rule.location_src_id,
            "destination": destination,
        }

    @api.model
    def _sort_locations(self, rules_and_loc, warehouses):
        """Order the locations left-to-right along the flow of goods.

        Rules define a directed graph (source -> destination) over the
        locations. We lay them out so that, as much as possible, a rule's
        source sits left of its destination (a topological order), then group
        that order by role: supplier/production locations first, then the
        internal locations of each selected warehouse, then customer locations,
        then anything left (views, transit, unmatched warehouses).
        """
        Location = self.env["stock.location"]
        sources = Location.union(*(rl["source"] for rl in rules_and_loc))
        destinations = Location.union(*(rl["destination"] for rl in rules_and_loc))
        all_locations = sources | destinations
        edges = [
            (rl["source"], rl["destination"])
            for rl in rules_and_loc
            if rl["source"] and rl["destination"]
        ]

        topo_rank = self._topological_rank(all_locations, edges)
        warehouse_rank = {wh.id: idx for idx, wh in enumerate(warehouses)}

        def group_key(location):
            if location.usage in ("supplier", "production"):
                return 0
            if location.usage == "customer":
                return 3
            wh = location.warehouse_id
            if wh and wh.id in warehouse_rank:
                return 1 + warehouse_rank[wh.id] / (len(warehouse_rank) + 1)
            return 2

        return all_locations.sorted(key=lambda loc: (group_key(loc), topo_rank[loc.id]))

    @api.model
    def _topological_rank(self, locations, edges):
        """Return ``{location_id: rank}`` following a Kahn topological sort.

        Deterministic (ties broken by id) and cycle-safe: any location left in a
        cycle is appended in id order after the acyclic part.
        """
        location_ids = set(locations.ids)
        successors = defaultdict(set)
        indegree = dict.fromkeys(location_ids, 0)
        for source, destination in edges:
            if source.id == destination.id:
                continue
            if destination.id not in successors[source.id]:
                successors[source.id].add(destination.id)
                indegree[destination.id] += 1

        ready = sorted(lid for lid, deg in indegree.items() if deg == 0)
        rank = {}
        while ready:
            lid = ready.pop(0)
            rank[lid] = len(rank)
            newly_ready = []
            for succ in successors[lid]:
                indegree[succ] -= 1
                if indegree[succ] == 0:
                    newly_ready.append(succ)
            # keep the frontier sorted for a stable, id-ordered result
            for succ in sorted(newly_ready):
                ready.insert(0, succ)
            ready.sort()
        # locations still stuck in a cycle: append deterministically
        for lid in sorted(location_ids - rank.keys()):
            rank[lid] = len(rank)
        return rank
