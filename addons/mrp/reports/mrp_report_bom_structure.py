from collections import OrderedDict, defaultdict
from datetime import date, datetime, time, timedelta

from odoo import api, fields, models
from odoo.exceptions import UserError
from odoo.libs.debug_log import DebugLog
from odoo.tools import (
    float_repr,
    float_round,
    format_date,
)

_debug = DebugLog(__name__)


class ReportMrpReport_Bom_Structure(models.AbstractModel):
    _name = "report.mrp.report_bom_structure"
    _description = "BOM Overview Report"

    @api.model
    def _get_default_warehouse(self, bom):
        if warehouse_id := self.env.context.get("warehouse_id"):
            return self.env["stock.warehouse"].browse(warehouse_id)
        company = bom.company_id or self.env.company
        return self.env["stock.warehouse"].search(
            [("company_id", "=", company.id)], limit=1
        )

    def _with_bom_company(self, bom):
        if not bom.company_id or bom.company_id == self.env.company:
            return self
        return self.with_company(bom.company_id)

    @api.model
    def _get_current_production_capacity(self, bom_data):
        components_qty_to_produce = defaultdict(lambda: 0)
        components_qty_available = {}
        for comp in bom_data.get("components", []):
            product = comp["product"]
            if not product.is_storable or comp["uom"].is_zero(
                comp["base_bom_line_qty"]
            ):
                continue
            components_qty_to_produce[product.id] += comp["uom"]._get_quantity_report(
                comp["base_bom_line_qty"], product.uom_id
            )
            components_qty_available[product.id] = comp["uom"]._get_quantity_report(
                comp["free_to_manufacture_qty"], product.uom_id
            )
        producibles = [
            float_round(
                components_qty_available[p_id] / qty,
                precision_digits=0,
                rounding_method="DOWN",
            )
            for p_id, qty in components_qty_to_produce.items()
        ]
        return min(producibles) * bom_data["bom"]["product_qty"] if producibles else 0

    @api.model
    def _get_report_values(self, docids, data=None):
        docs = []
        for bom in self.env["mrp.bom"].browse(docids):
            variants = bom.product_id or bom.product_tmpl_id.product_variant_ids
            docs.extend(
                self._get_pdf_line(bom.id, product_id=variant.id, qty=bom.product_qty)
                for variant in variants
            )
            if not variants:
                docs.append(self._get_pdf_line(bom.id, qty=bom.product_qty))
        return {
            "doc_ids": docids,
            "doc_model": "mrp.bom",
            "docs": docs,
        }

    @api.model
    def _get_report_data(self, bom_id, searchQty=0, searchVariant=False):
        lines = {}
        self = self._with_bom_company(self.env["mrp.bom"].browse(bom_id))
        bom = self.env["mrp.bom"].browse(bom_id)
        bom_quantity = searchQty or bom.product_qty or 1
        bom_product_variants = {}
        bom_uom_name = ""

        if searchVariant:
            product = self.env["product.product"].browse(int(searchVariant))
        else:
            product = (
                bom.product_id
                or bom.product_tmpl_id.product_variant_id
                or bom.product_tmpl_id.with_context(
                    active_test=False
                ).product_variant_ids[:1]
            )

        if bom:
            bom_uom_name = bom.product_uom_id.name

            if not bom.product_id:
                for variant in bom.product_tmpl_id.product_variant_ids:
                    bom_product_variants[variant.id] = variant.display_name

        warehouse = self._get_default_warehouse(bom)

        with _debug.perf(
            "bom_structure_report",
            cr=self.env.cr,
            bom=bom_id,
            quantity=bom_quantity,
            warehouse=warehouse.id,
            variant=bool(searchVariant),
        ):
            lines = self._get_bom_data(
                bom, warehouse, product=product, line_qty=bom_quantity, level=0
            )
        return {
            "lines": lines,
            "variants": bom_product_variants,
            "bom_uom_name": bom_uom_name,
            "bom_qty": bom_quantity,
            "is_variant_applied": self.env.user.has_group(
                "product.group_product_variant"
            )
            and len(bom_product_variants) > 1,
            "is_uom_applied": self.env.user.has_group("uom.group_uom"),
            "precision": self.env["decimal.precision"].get_precision("Product Unit"),
        }

    @api.model
    def _get_missing_qty_status(self, missing_qty, route_name):
        missing_qty = max(missing_qty, 0)
        if not missing_qty:
            return ""
        return self.env._(
            "%(qty)s To %(route)s",
            qty=float_repr(
                missing_qty,
                self.env["decimal.precision"].get_precision("Product Unit"),
            ),
            route=route_name or self.env._("Order"),
        )

    @api.model
    def _get_bom_components_data(
        self,
        bom,
        product,
        warehouse,
        current_quantity,
        level,
        index,
        product_info,
        ignore_stock,
        simulated_leaves_per_workcenter,
    ):
        no_bom_lines = self.env["mrp.bom.line"]
        line_quantities = {}
        for line in bom.bom_line_ids:
            if product and line._is_bom_line_skipped(product):
                continue
            line_quantity = (
                current_quantity / (bom.product_qty or 1.0)
            ) * line.product_qty
            line_quantities[line.id] = line_quantity
            if line.child_bom_id:
                continue
            no_bom_lines |= line
            self._update_product_info(
                line.product_id,
                bom.id,
                product_info,
                warehouse,
                line.product_uom_id._get_quantity_report(
                    line_quantity, line.product_id.uom_id
                ),
                bom=False,
                parent_bom=bom,
                parent_product=product,
            )
        components_closest_forecasted = self._get_components_closest_forecasted(
            no_bom_lines, line_quantities, bom, product_info, product, ignore_stock
        )

        components = []
        for component_index, line in enumerate(bom.bom_line_ids):
            if product and line._is_bom_line_skipped(product):
                continue
            new_index = f"{index}{component_index}"
            line_quantity = line_quantities.get(line.id, 0.0)
            if line.child_bom_id:
                component = self._get_bom_data(
                    line.child_bom_id,
                    warehouse,
                    line.product_id,
                    line_quantity,
                    bom_line=line,
                    level=level + 1,
                    parent_bom=bom,
                    parent_product=product,
                    index=new_index,
                    product_info=product_info,
                    ignore_stock=ignore_stock,
                    simulated_leaves_per_workcenter=simulated_leaves_per_workcenter,
                )
            else:
                component = self.with_context(
                    components_closest_forecasted=components_closest_forecasted,
                )._get_component_data(
                    bom,
                    product,
                    warehouse,
                    line,
                    line_quantity,
                    level + 1,
                    new_index,
                    product_info,
                    ignore_stock,
                )
            for component_bom in components:
                if (
                    component["product_id"] == component_bom["product_id"]
                    and component["uom"].id == component_bom["uom"].id
                ):
                    self._merge_components(component_bom, component)
                    break
            else:
                components.append(component)
        return components

    @api.model
    def _get_components_closest_forecasted(
        self,
        lines,
        line_quantities,
        parent_bom,
        product_info,
        parent_product,
        ignore_stock=False,
    ):
        if ignore_stock:
            return {}
        closest_forecasted = defaultdict(OrderedDict)
        remaining_products = []
        product_quantities_info = defaultdict(OrderedDict)
        for line in lines:
            product = line.product_id
            line_quantity = line_quantities.get(line.id, 0.0)
            quantities_info = self._get_quantities_info(
                product, line.product_uom_id, product_info, parent_bom, parent_product
            )
            stock_loc = quantities_info["stock_loc"]
            consumptions = product_info[product.id]["consumptions"]
            consumptions[stock_loc] += line.product_uom_id._get_quantity_report(
                line_quantity, product.uom_id, round=False
            )
            product_quantities_info[product.id][line.id] = consumptions[stock_loc]
            qty_free = line.product_uom_id._get_quantity_report(
                quantities_info["qty_free"], product.uom_id, round=False
            )
            if (
                not product.is_storable
                or product.uom_id.compare(consumptions[stock_loc], qty_free) <= 0
            ):
                closest_forecasted[product.id][line.id] = date.min
            elif (
                stock_loc != "in_stock"
                or quantities_info["forecasted_qty"] < line_quantity
            ):
                closest_forecasted[product.id][line.id] = date.max
            else:
                remaining_products.append(product.id)
                closest_forecasted[product.id][line.id] = None
        date_today = self.env.context.get("from_date", fields.Date.today())
        domain = [
            ("state", "=", "forecast"),
            ("date", ">=", date_today),
            ("product_id", "in", list(set(remaining_products))),
        ]
        if self.env.context.get("warehouse_id"):
            domain.append(("warehouse_id", "=", self.env.context.get("warehouse_id")))
        if remaining_products:
            res = self.env["report.stock.quantity"]._read_group(
                domain,
                groupby=["product_id", "product_qty"],
                aggregates=["date:min"],
                order="product_id asc, date:min asc",
            )
            available_quantities = defaultdict(list)
            for group in res:
                product_id = group[0].id
                available_quantities[product_id].append([group[2], group[1]])
            for product_id in remaining_products:
                line_id = next(
                    filter(
                        lambda k: not closest_forecasted[product_id][k],
                        closest_forecasted[product_id].keys(),
                    ),
                    None,
                )
                for min_date, product_qty in available_quantities[product_id]:
                    if product_qty >= product_quantities_info[product_id][line_id]:
                        closest_forecasted[product_id][line_id] = min_date
                        break
                if not closest_forecasted[product_id][line_id]:
                    closest_forecasted[product_id][line_id] = date.max
        return closest_forecasted

    @api.model
    def _get_bom_data(
        self,
        bom,
        warehouse,
        product=False,
        line_qty=False,
        bom_line=False,
        level=0,
        parent_bom=False,
        parent_product=False,
        index=0,
        product_info=False,
        ignore_stock=False,
        simulated_leaves_per_workcenter=False,
    ):
        is_minimized = self.env.context.get("minimized", False)
        if not product:
            product = bom.product_id or bom.product_tmpl_id.product_variant_id
        if line_qty is False:
            line_qty = bom.product_qty
        if not product_info:
            product_info = {}
        if simulated_leaves_per_workcenter is False:
            simulated_leaves_per_workcenter = defaultdict(list)

        company = bom.company_id or self.env.company
        current_quantity = line_qty
        if bom_line:
            current_quantity = (
                bom_line.product_uom_id._get_quantity_report(
                    line_qty, bom.product_uom_id, round=False
                )
                or 0
            )

        key = product.id
        bom_key = bom.id
        qty_product_uom = bom.product_uom_id._get_quantity_report(
            current_quantity, product.uom_id or bom.product_tmpl_id.uom_id
        )
        self._update_product_info(
            product,
            bom_key,
            product_info,
            warehouse,
            qty_product_uom,
            bom=bom,
            parent_bom=parent_bom,
            parent_product=parent_product,
        )
        route_info = product_info[key].get(bom_key, {})
        quantities_info = {}
        if not ignore_stock:
            quantities_info = self._get_quantities_info(
                product, bom.product_uom_id, product_info, parent_bom, parent_product
            )

        bom_report_line = {
            "index": index,
            "bom": bom,
            "bom_id": (bom and bom.id) or False,
            "bom_code": (bom and bom.code) or False,
            "type": "bom",
            "is_storable": product.is_storable,
            "quantity": current_quantity,
            "quantity_available": quantities_info.get("qty_free") or 0,
            "quantity_on_hand": quantities_info.get("on_hand_qty") or 0,
            "quantity_forecasted": quantities_info.get("forecasted_qty") or 0,
            "free_to_manufacture_qty": quantities_info.get("free_to_manufacture_qty")
            or 0,
            "base_bom_line_qty": bom_line.product_uom_id._get_quantity_report(
                bom_line.product_qty, bom.product_uom_id, round=False
            )
            if bom_line
            else False,
            "name": product.display_name or bom.product_tmpl_id.display_name,
            "uom": bom.product_uom_id if bom else product.uom_id,
            "uom_name": bom.product_uom_id.name if bom else product.uom_id.name,
            "route_type": route_info.get("route_type", ""),
            "route_name": route_info.get("route_name", ""),
            "route_detail": route_info.get("route_detail", ""),
            "route_alert": route_info.get("route_alert", False),
            "route_record": route_info.get("bom") or route_info.get("supplier"),
            "currency": company.currency_id,
            "currency_id": company.currency_id.id,
            "product": product,
            "product_id": product.id,
            "product_template_id": product.product_tmpl_id.id,
            "code": (bom and bom.display_name) or "",
            "bom_cost": 0,
            "level": level or 0,
            "phantom_bom": bom.type == "phantom",
            "parent_id": (parent_bom and parent_bom.id) or False,
        }

        components = self._get_bom_components_data(
            bom,
            product,
            warehouse,
            current_quantity,
            level,
            index,
            product_info,
            ignore_stock,
            simulated_leaves_per_workcenter,
        )
        for component in components:
            if not component["is_storable"]:
                continue
            if status := self._get_missing_qty_status(
                component["quantity"] - component["quantity_forecasted"],
                component["route_name"],
            ):
                component["status"] = status
        bom_report_line["components"] = components
        bom_report_line["producible_qty"] = self._get_current_production_capacity(
            bom_report_line
        )

        availabilities = self._get_availabilities(
            product,
            current_quantity,
            product_info,
            bom_key,
            quantities_info,
            level,
            ignore_stock,
            components,
            report_line=bom_report_line,
            uom=bom.product_uom_id,
        )
        bom_report_line["lead_time"] = route_info.get("lead_time", False)
        bom_report_line["manufacture_delay"] = route_info.get(
            "manufacture_delay", False
        )
        bom_report_line.update(availabilities)

        if level == 0:
            bom_report_line["status"] = (
                self.env._(
                    "%(qty)s Ready To Produce", qty=bom_report_line["producible_qty"]
                )
                if bom_report_line["producible_qty"] > 0
                else self.env._("No Ready To Produce")
            )
        elif status := self._get_missing_qty_status(
            bom_report_line["quantity"] - bom_report_line["quantity_available"],
            bom_report_line["route_name"],
        ):
            bom_report_line["status"] = status

        if not is_minimized:
            operations = self._get_operation_line(
                product,
                bom,
                current_quantity,
                level + 1,
                index,
                bom_report_line,
                simulated_leaves_per_workcenter,
                as_component=bool(bom_line),
            )
            bom_report_line["operations"] = operations
            bom_report_line["operations_cost"] = sum(
                op["bom_cost"] for op in operations
            )
            bom_report_line["operations_time"] = sum(
                op["quantity"] for op in operations
            )
            bom_report_line["operations_delay"] = max(
                (op["availability_delay"] for op in operations), default=0
            )
            if "simulated" in bom_report_line:
                bom_report_line["availability_state"] = "estimated"
                max_component_delay = bom_report_line["max_component_delay"]
                bom_report_line["availability_delay"] = max_component_delay + max(
                    bom_report_line["manufacture_delay"] or bom.produce_delay,
                    bom_report_line["operations_delay"],
                )
                bom_report_line["availability_display"] = self._format_date_display(
                    bom_report_line["availability_state"],
                    bom_report_line["availability_delay"],
                )
            rolled_up_cost = bom._get_rolled_up_cost(
                product, current_quantity, as_component=bool(bom_line)
            )
            byproducts = self._get_byproducts_lines(
                product,
                bom,
                current_quantity,
                level + 1,
                rolled_up_cost,
                index,
            )
            bom_report_line["byproducts"] = byproducts
            bom_report_line["cost_share"] = bom._get_finished_cost_share(product)
            bom_report_line["byproducts_cost"] = sum(
                byproduct["bom_cost"] for byproduct in byproducts
            )
            bom_report_line["byproducts_total"] = sum(
                byproduct["quantity"] for byproduct in byproducts
            )
            bom_report_line["bom_cost"] = rolled_up_cost * bom_report_line["cost_share"]
            if bom_line and bom.type != "phantom":
                standard_cost = company.currency_id.round(
                    product._get_standard_cost(
                        current_quantity, bom.product_uom_id, company
                    )
                )
                if company.currency_id.compare_amounts(
                    standard_cost, bom_report_line["bom_cost"]
                ):
                    bom_report_line["standard_cost"] = standard_cost

        bom_report_line["foldable"] = (
            len(bom.operation_ids) > 0
            or (len(bom_report_line["components"]) > 0 and level > 0)
            or any(
                component.get("foldable", False)
                for component in bom_report_line["components"]
            )
        )

        if level == 0:
            bom_report_line["components_available"] = all(
                c["stock_avail_state"] == "available" for c in components
            )
        _debug.pipeline(
            "bom_data_built", bom=bom.id, level=level, components=len(components)
        )
        return bom_report_line

    @api.model
    def _get_component_data(
        self,
        parent_bom,
        parent_product,
        warehouse,
        bom_line,
        line_quantity,
        level,
        index,
        product_info,
        ignore_stock=False,
    ):
        company = parent_bom.company_id or self.env.company
        rounded_price = company.currency_id.round(
            bom_line.product_id._get_standard_cost(
                line_quantity, bom_line.product_uom_id, company
            )
        )

        key = bom_line.product_id.id
        bom_key = parent_bom.id
        route_info = product_info[key].get(bom_key, {})

        quantities_info = {}
        if not ignore_stock:
            quantities_info = self._get_quantities_info(
                bom_line.product_id,
                bom_line.product_uom_id,
                product_info,
                parent_bom,
                parent_product,
            )
        availabilities = self._get_availabilities(
            bom_line.product_id,
            line_quantity,
            product_info,
            bom_key,
            quantities_info,
            level,
            ignore_stock,
            bom_line=bom_line,
            uom=bom_line.product_uom_id,
        )

        return {
            "type": "component",
            "index": index,
            "bom_id": False,
            "product": bom_line.product_id,
            "product_id": bom_line.product_id.id,
            "product_template_id": bom_line.product_tmpl_id.id,
            "name": bom_line.product_id.display_name,
            "code": "",
            "currency": company.currency_id,
            "currency_id": company.currency_id.id,
            "is_storable": bom_line.product_id.is_storable,
            "quantity": line_quantity,
            "quantity_available": quantities_info.get("qty_free", 0),
            "quantity_on_hand": quantities_info.get("on_hand_qty", 0),
            "quantity_forecasted": quantities_info.get("forecasted_qty", 0),
            "free_to_manufacture_qty": quantities_info.get(
                "free_to_manufacture_qty", 0
            ),
            "base_bom_line_qty": bom_line.product_qty,
            "uom": bom_line.product_uom_id,
            "uom_name": bom_line.product_uom_id.name,
            "bom_cost": rounded_price,
            "route_type": route_info.get("route_type", ""),
            "route_name": route_info.get("route_name", ""),
            "route_detail": route_info.get("route_detail", ""),
            "route_alert": route_info.get("route_alert", False),
            "route_record": route_info.get("bom") or route_info.get("supplier"),
            "lead_time": route_info.get("lead_time", False),
            "manufacture_delay": route_info.get("manufacture_delay", False),
            "stock_avail_state": availabilities["stock_avail_state"],
            "resupply_avail_delay": availabilities["resupply_avail_delay"],
            "availability_display": availabilities["availability_display"],
            "availability_state": availabilities["availability_state"],
            "availability_delay": availabilities["availability_delay"],
            "parent_id": parent_bom.id,
            "level": level or 0,
        }

    @api.model
    def _get_quantities_info(
        self, product, bom_uom, product_info, parent_bom=False, parent_product=False
    ):
        stock = product._get_stock_in_unit(bom_uom)
        quantities_info = {
            "qty_free": stock["free"],
            "on_hand_qty": stock["on_hand"],
            "forecasted_qty": stock["forecasted"],
            "stock_loc": "in_stock",
        }
        quantities_info["free_to_manufacture_qty"] = quantities_info["qty_free"]
        return quantities_info

    @api.model
    def _update_product_info(
        self,
        product,
        bom_key,
        product_info,
        warehouse,
        quantity,
        bom,
        parent_bom,
        parent_product,
    ):
        key = product.id
        if key not in product_info:
            product_info[key] = {"consumptions": {"in_stock": 0}}
        if not product_info[key].get(bom_key):
            product_info[key][bom_key] = self._get_resupply_route_info(
                warehouse,
                product,
                quantity,
                product_info,
                bom,
                parent_bom,
                parent_product,
            )
        elif product_info[key][bom_key].get("route_alert"):
            product_info[key][bom_key] = self._get_resupply_route_info(
                warehouse,
                product,
                quantity + product_info[key][bom_key].get("qty_checked"),
                product_info,
                bom,
                parent_bom,
                parent_product,
            )

    @api.model
    def _get_byproducts_lines(self, product, bom, bom_quantity, level, total, index):
        byproducts = []
        company = bom.company_id or self.env.company
        for byproduct_index, (byproduct, cost_share) in enumerate(
            bom._get_byproduct_cost_shares(product).items()
        ):
            line_quantity = (
                bom_quantity / (bom.product_qty or 1.0)
            ) * byproduct.product_qty
            byproducts.append(
                {
                    "id": byproduct.id,
                    "index": f"{index}{byproduct_index}",
                    "type": "byproduct",
                    "product_id": byproduct.product_id.id,
                    "currency_id": company.currency_id.id,
                    "name": byproduct.product_id.display_name,
                    "quantity": line_quantity,
                    "uom_name": byproduct.product_uom_id.name,
                    "parent_id": bom.id,
                    "level": level or 0,
                    "bom_cost": company.currency_id.round(total * cost_share),
                    "cost_share": cost_share,
                }
            )
        return byproducts

    @api.model
    def _get_operation_line(
        self,
        product,
        bom,
        qty,
        level,
        index,
        bom_report_line,
        simulated_leaves_per_workcenter,
        as_component=False,
    ):
        operations = []
        company = bom.company_id or self.env.company
        costed_qty, scale = bom._get_costing_quantity(qty, as_component)
        operations_planning = {}
        if (
            bom_report_line["availability_state"] in ["unavailable", "estimated"]
            and bom.operation_ids
        ):
            qty_requested = bom.product_uom_id._get_quantity_report(
                qty, bom.product_tmpl_id.uom_id
            )
            qty_to_produce = bom.product_tmpl_id.uom_id._get_quantity_report(
                max(
                    0,
                    qty_requested - (product.qty_available_virtual if level > 1 else 0),
                ),
                bom.product_uom_id,
            )
            if not (product or bom.product_tmpl_id).uom_id.is_zero(qty_to_produce):
                max_component_delay = 0
                for component in bom_report_line["components"]:
                    line_delay = component.get("availability_delay", 0)
                    max_component_delay = max(max_component_delay, line_delay)
                date_today = self.env.context.get(
                    "from_date", fields.Date.today()
                ) + timedelta(days=max_component_delay)
                operations_planning = self._simulate_bom_planning(
                    bom,
                    product,
                    datetime.combine(date_today, time.min),
                    qty_to_produce,
                    simulated_leaves_per_workcenter=simulated_leaves_per_workcenter,
                )
                bom_report_line["simulated"] = True
                bom_report_line["max_component_delay"] = max_component_delay
        operation_index = 0
        for operation in bom.operation_ids:
            if not product or operation._is_bom_line_skipped(product):
                continue
            op = operation._for_demand(product, costed_qty, bom.product_uom_id)
            duration_expected = op.time_total * scale
            bom_cost = company.currency_id.round(op.cost * scale)
            if planning := operations_planning.get(operation, None):
                availability_state = "estimated"
                availability_delay = (planning["date_end"].date() - date_today).days
                availability_display = self.env._(
                    "Estimated %s", format_date(self.env, planning["date_end"])
                ) + (
                    " [" + planning["workcenter"].name + "]"
                    if planning["workcenter"] != operation.workcenter_id
                    else ""
                )
            else:
                availability_state = "available"
                availability_delay = 0
                availability_display = ""
            operations.append(
                {
                    "type": "operation",
                    "index": f"{index}{operation_index}",
                    "level": level or 0,
                    "operation": operation,
                    "name": operation.name + " - " + operation.workcenter_id.name,
                    "uom_name": self.env._("Minutes"),
                    "quantity": duration_expected,
                    "bom_cost": bom_cost,
                    "currency_id": company.currency_id.id,
                    "model": "mrp.routing.workcenter",
                    "availability_state": availability_state,
                    "availability_delay": availability_delay,
                    "availability_display": availability_display,
                }
            )
            operation_index += 1
        return operations

    @api.model
    def _get_pdf_line(self, bom_id, product_id=False, qty=1):
        self = self._with_bom_company(self.env["mrp.bom"].browse(bom_id))
        bom = self.env["mrp.bom"].browse(bom_id)
        if product_id:
            product = self.env["product.product"].browse(int(product_id))
        else:
            product = (
                bom.product_id
                or bom.product_tmpl_id.product_variant_id
                or bom.product_tmpl_id.with_context(
                    active_test=False
                ).product_variant_ids[:1]
            )

        warehouse = self._get_default_warehouse(bom)
        data = self._get_bom_data(
            bom, warehouse, product=product, line_qty=qty, level=0
        )
        data["lines"] = self._get_bom_array_lines(data, 1)
        return data

    @api.model
    def _get_bom_array_lines(self, data, level):
        lines = []
        for bom_line in data["components"]:
            lines.append(
                {
                    "name": bom_line["name"],
                    "type": bom_line["type"],
                    "quantity": bom_line["quantity"],
                    "uom": bom_line["uom_name"],
                    "bom_cost": bom_line["bom_cost"],
                    "standard_cost": bom_line.get("standard_cost"),
                    "level": bom_line["level"],
                }
            )
            if bom_line.get("components"):
                lines += self._get_bom_array_lines(bom_line, level + 1)

        if data["operations"]:
            lines.append(
                {
                    "name": self.env._("Operations"),
                    "type": "operation",
                    "quantity": data["operations_time"],
                    "uom": self.env._("minutes"),
                    "bom_cost": data["operations_cost"],
                    "level": level,
                }
            )
            lines.extend(
                {
                    "name": operation["name"],
                    "type": "operation",
                    "quantity": operation["quantity"],
                    "uom": self.env._("minutes"),
                    "bom_cost": operation["bom_cost"],
                    "level": level + 1,
                }
                for operation in data["operations"]
            )
        if data["byproducts"]:
            lines.append(
                {
                    "name": self.env._("Byproducts"),
                    "type": "byproduct",
                    "uom": False,
                    "quantity": data["byproducts_total"],
                    "bom_cost": data["byproducts_cost"],
                    "level": level,
                }
            )
            lines.extend(
                {
                    "name": byproduct["name"],
                    "type": "byproduct",
                    "quantity": byproduct["quantity"],
                    "uom": byproduct["uom_name"],
                    "bom_cost": byproduct["bom_cost"],
                    "level": level + 1,
                }
                for byproduct in data["byproducts"]
            )
        return lines

    @api.model
    def _get_resupply_route_info(
        self,
        warehouse,
        product,
        quantity,
        product_info,
        bom=False,
        parent_bom=False,
        parent_product=False,
    ):
        found_rules = []
        if self._has_special_rules(product_info, parent_bom, parent_product):
            found_rules = self._get_special_rules(
                product, product_info, bom, parent_bom, parent_product
            )
        if not found_rules and warehouse:
            found_rules = product._get_rules_from_location(warehouse.lot_stock_id)
        if not found_rules:
            return {}
        return self._format_route_info(found_rules, warehouse, product, bom, quantity)

    @api.model
    def _is_resupply_rules(self, rules, bom):
        return bom and any(rule.action == "manufacture" for rule in rules)

    @api.model
    def _has_special_rules(self, product_info, parent_bom=False, parent_product=False):
        return False

    @api.model
    def _get_special_rules(
        self,
        product,
        product_info,
        current_bom=False,
        parent_bom=False,
        parent_product=False,
    ):
        return False

    @api.model
    def _format_route_info(self, rules, warehouse, product, bom, quantity):
        manufacture_rules = [
            rule for rule in rules if rule.action == "manufacture" and bom
        ]
        if manufacture_rules:
            delays, _description = rules.with_context(
                bypass_delay_description=True
            )._get_lead_days(product, bom_id=bom)
            return {
                "route_type": "manufacture",
                "route_name": manufacture_rules[0].route_id.display_name,
                "route_detail": bom.display_name,
                "lead_time": delays["total_delay"],
                "manufacture_delay": delays["total_delay"] - bom.days_to_prepare_mo,
                "bom": bom,
            }
        return {}

    @api.model
    def _get_availabilities(
        self,
        product,
        quantity,
        product_info,
        bom_key,
        quantities_info,
        level,
        ignore_stock=False,
        components=False,
        bom_line=None,
        report_line=False,
        uom=None,
    ):
        stock_state, stock_delay = ("unavailable", False)
        if not ignore_stock:
            stock_state, stock_delay = self._get_stock_availability(
                product,
                quantity,
                product_info,
                quantities_info,
                bom_line=bom_line,
                uom=uom,
            )

        components = components or []
        route_info = product_info[product.id].get(bom_key)
        resupply_state, resupply_delay = ("unavailable", False)
        if product and not product.is_storable:
            resupply_state, resupply_delay = ("available", 0)
        elif route_info:
            resupply_state, resupply_delay = self._get_resupply_availability(
                route_info, components
            )

        if (
            resupply_state == "unavailable"
            and route_info == {}
            and components
            and report_line
            and report_line["phantom_bom"]
        ):
            _debug.logic(
                "availability", product=product.id, by="phantom_last_component"
            )
            return self._get_last_availability(report_line)

        base = {
            "resupply_avail_delay": resupply_delay,
            "stock_avail_state": stock_state,
        }
        _debug.logic(
            "availability",
            product=product.id,
            level=level,
            by="stock" if level != 0 and stock_state != "unavailable" else "resupply",
            stock_state=stock_state,
            resupply_state=resupply_state,
        )
        if level != 0 and stock_state != "unavailable":
            return {
                **base,
                "availability_display": self._format_date_display(
                    stock_state, stock_delay
                ),
                "availability_state": stock_state,
                "availability_delay": stock_delay,
            }
        return {
            **base,
            "availability_display": self._format_date_display(
                resupply_state, resupply_delay
            ),
            "availability_state": resupply_state,
            "availability_delay": resupply_delay,
        }

    @api.model
    def _get_stock_availability(
        self,
        product,
        quantity,
        product_info,
        quantities_info,
        bom_line=None,
        uom=None,
    ):
        closest_forecasted = None
        if bom_line:
            closest_forecasted = (
                self.env.context.get("components_closest_forecasted", {})
                .get(product.id, {})
                .get(bom_line.id)
            )
        if closest_forecasted == date.min:
            return ("available", 0)
        if closest_forecasted == date.max:
            return ("unavailable", False)
        date_today = self.env.context.get("from_date", fields.Date.today())
        if product and not product.is_storable:
            return ("available", 0)
        if closest_forecasted:
            # _get_components_closest_forecasted already counted this consumption
            return ("expected", (closest_forecasted - date_today).days)

        unit = uom or product.uom_id
        stock_loc = quantities_info["stock_loc"]
        consumptions = product_info[product.id]["consumptions"]
        consumptions[stock_loc] += unit._get_quantity_report(
            quantity, product.uom_id, round=False
        )
        qty_free = unit._get_quantity_report(
            quantities_info["qty_free"], product.uom_id, round=False
        )
        if product and product.uom_id.compare(consumptions[stock_loc], qty_free) <= 0:
            return ("available", 0)

        if stock_loc == "in_stock":
            domain = [
                ("state", "=", "forecast"),
                ("date", ">=", date_today),
                ("product_id", "=", product.id),
                ("product_qty", ">=", consumptions[stock_loc]),
            ]
            if self.env.context.get("warehouse_id"):
                domain.append(
                    ("warehouse_id", "=", self.env.context.get("warehouse_id"))
                )
            [closest_forecasted] = self.env["report.stock.quantity"]._read_group(
                domain, aggregates=["date:min"]
            )[0]
            if closest_forecasted:
                days_to_forecast = (closest_forecasted - date_today).days
                return ("expected", days_to_forecast)
        return ("unavailable", False)

    @api.model
    def _get_resupply_availability(self, route_info, components):
        if route_info.get("route_type") == "manufacture":
            max_component_delay = self._get_max_component_delay(components)
            if max_component_delay is False:
                return ("unavailable", False)
            produce_delay = route_info.get("manufacture_delay", 0) + max_component_delay
            return ("estimated", produce_delay)
        return ("unavailable", False)

    @api.model
    def _get_max_component_delay(self, components):
        max_component_delay = 0
        for component in components:
            line_delay = component.get("availability_delay", False)
            if line_delay is False:
                return False
            max_component_delay = max(max_component_delay, line_delay)
        return max_component_delay

    @api.model
    def _format_date_display(self, state, delay):
        date_today = self.env.context.get("from_date", fields.Date.today())
        day = date_today + timedelta(days=delay) if delay else date_today
        return self.env["report.mrp.report_mo_overview"]._format_receipt_date(
            state, day
        )["display"]

    def _merge_components(self, component_1, component_2):
        component_1["quantity"] += component_2["quantity"]
        component_1["base_bom_line_qty"] += component_2["base_bom_line_qty"]
        component_1["bom_cost"] += component_2["bom_cost"]
        if component_2.get("availability_delay") is False or component_2.get(
            "availability_delay"
        ) >= component_1.get("availability_delay"):
            component_1.update(self._format_availability(component_2))
        if not component_1.get("components"):
            return
        for index in range(len(component_1.get("components"))):
            self._merge_components(
                component_1["components"][index], component_2["components"][index]
            )

    def _get_last_availability(self, report_line):
        delay = 0
        component_max_delay = False
        for component in report_line["components"]:
            if component["availability_delay"] is False:
                component_max_delay = component
                break
            if component["availability_delay"] >= delay:
                component_max_delay = component
                delay = component["availability_delay"]
        return self._format_availability(component_max_delay)

    def _format_availability(self, component):
        return {
            "resupply_avail_delay": component["resupply_avail_delay"],
            "stock_avail_state": component["stock_avail_state"],
            "availability_display": component["availability_display"],
            "availability_state": component["availability_state"],
            "availability_delay": component["availability_delay"],
        }

    def _simulate_bom_planning(
        self, bom, product, start_date, quantity, simulated_leaves_per_workcenter=False
    ):
        bom.check_singleton()
        if not bom.operation_ids:
            return {}
        if not product:
            product = bom.product_id or bom.product_tmpl_id.product_variant_id
        planning_per_operation = {}
        if simulated_leaves_per_workcenter is False:
            simulated_leaves_per_workcenter = defaultdict(list)
        if bom.allow_operation_dependencies:
            final_operations = bom.operation_ids.filtered(
                lambda o: not o.needed_by_operation_ids
            )
            for operation in final_operations:
                if operation._is_bom_line_skipped(product):
                    continue
                self._simulate_operation_planning(
                    operation,
                    product,
                    start_date,
                    quantity,
                    planning_per_operation,
                    simulated_leaves_per_workcenter,
                )
        else:
            for operation in bom.operation_ids:
                if operation._is_bom_line_skipped(product):
                    continue
                self._simulate_operation_planning(
                    operation,
                    product,
                    start_date,
                    quantity,
                    planning_per_operation,
                    simulated_leaves_per_workcenter,
                )
                start_date = planning_per_operation[operation]["date_end"]
        return planning_per_operation

    def _simulate_operation_planning(
        self,
        operation,
        product,
        start_date,
        quantity,
        planning_per_operation=False,
        simulated_leaves_per_workcenter=False,
    ):
        operation.check_singleton()
        if planning_per_operation is False:
            planning_per_operation = {}
        if simulated_leaves_per_workcenter is False:
            simulated_leaves_per_workcenter = defaultdict(list)
        date_start = max(start_date, datetime.now())
        for op in operation.blocked_by_operation_ids:
            if op._is_bom_line_skipped(product):
                continue
            if op not in planning_per_operation:
                self._simulate_operation_planning(
                    op,
                    product,
                    start_date,
                    quantity,
                    planning_per_operation,
                    simulated_leaves_per_workcenter,
                )
            date_start = max(date_start, planning_per_operation[op]["date_end"])
        workcenters = (
            operation.workcenter_id | operation.workcenter_id.alternative_workcenter_ids
        )
        best, reasons = workcenters._get_earliest_slot_and_reasons(
            date_start,
            {
                workcenter: operation._for_demand(
                    product, quantity, operation.bom_id.product_uom_id
                )
                .with_context(workcenter=workcenter)
                .time_total
                for workcenter in workcenters
            },
            extra_leaves_by_workcenter=simulated_leaves_per_workcenter,
        )
        if best is None:
            raise UserError(
                workcenters._prepare_unplannable_error(operation.display_name, reasons)
            )
        best_workcenter, best_date_start, best_date_finished, best_duration_expected = (
            best
        )
        planning_per_operation[operation] = {
            "date_start": best_date_start,
            "date_end": best_date_finished,
            "workcenter": best_workcenter,
            "duration_expected": best_duration_expected,
        }
        simulated_leaves_per_workcenter[best_workcenter].append(
            (best_date_start, best_date_finished)
        )
        return planning_per_operation
