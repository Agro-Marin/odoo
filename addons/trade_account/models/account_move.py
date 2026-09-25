from odoo import models
from odoo.exceptions import UserError
from odoo.fields import Command
from odoo.libs.debug_log import DebugLog
from odoo.tools import OrderedSet

from odoo.addons.trade.tools import direction_of

_debug = DebugLog(__name__)


class AccountMove(models.Model):
    _inherit = "account.move"

    def _add_order_lines(self, order_lines):
        if not order_lines:
            return
        self.check_singleton()
        order_lines._assert_invoiced_uom_convertible()
        new_line_ids = self.env["account.move.line"]

        for order_line in order_lines:
            new_line_values = order_line._prepare_aml_vals(move=self)
            new_line_ids += self.env["account.move.line"].new(new_line_values)

        _debug.lifecycle(
            "order_lines_added_to_move", move=self, order_lines=order_lines
        )
        self.invoice_line_ids += new_line_ids

    def _compute_incoterm_location(self):
        super()._compute_incoterm_location()
        for move in self:
            location = next(
                (loc for loc in move._get_order_incoterm_locations() if loc),
                False,
            )
            if location:
                move.incoterm_location = location

    def _get_order_incoterm_locations(self):
        return []

    def _get_order_line_link_field(self, order_model):
        Line = self.env[self.env[order_model]._get_line_model()]
        return Line._get_invoice_line_link_field()

    def _get_source_orders(self, order_model):
        link = self._get_order_line_link_field(order_model)
        return self.line_ids.mapped(link).order_id

    def _is_matched_to_orders(self, order_model):
        self.check_singleton()
        link = self._get_order_line_link_field(order_model)
        return not any(
            line.display_type == "product" and not line[link]
            for line in self.invoice_line_ids
        )

    def _get_source_order_name(self, order_model):
        self.check_singleton()
        orders = self._get_source_orders(order_model)
        return orders.display_name if len(orders) == 1 else False

    def _get_order_warning_text(self, move_type, partner_field, product_field):
        self.check_singleton()
        if self.move_type != move_type:
            return ""
        warnings = OrderedSet()
        for partner in self.partner_id | self.partner_id.parent_id:
            if partner_msg := partner[partner_field]:
                warnings.add(
                    (partner.name or partner.display_name) + " - " + partner_msg
                )
        for product in self.invoice_line_ids.product_id:
            if product_msg := product[product_field]:
                warnings.add(product.display_name + " - " + product_msg)
        return "\n".join(warnings)

    def _auto_complete_from_order(self, match_field, order_field):
        match = self[match_field]
        if match.move_id:
            self.invoice_vendor_bill_id = match.move_id
            self._onchange_invoice_vendor_bill()
        elif match.order_id:
            self[order_field] = match.order_id
        self[match_field] = False

        order = self[order_field]
        if not order:
            _debug.logic("order_auto_complete_skipped", reason="no_order")
            return

        invoice_vals = order.with_company(order.company_id)._prepare_invoice_vals()
        has_invoice_lines = bool(
            self.invoice_line_ids.filtered(
                lambda line: (
                    line.display_type
                    not in ("line_section", "line_subsection", "line_note")
                ),
            ),
        )
        new_currency_id = (
            self.currency_id if has_invoice_lines else invoice_vals.get("currency_id")
        )
        del invoice_vals["company_id"]
        if self.move_type == invoice_vals["move_type"]:
            del invoice_vals["move_type"]
        self.update(invoice_vals)
        self.currency_id = new_currency_id

        link = self._get_order_line_link_field(order._name)
        order_lines = order.line_ids - self.invoice_line_ids.mapped(link)
        _debug.pipeline(
            "order_auto_complete",
            move=self._origin,
            order=order,
            added_lines=order_lines,
            had_lines=has_invoice_lines,
        )
        self._add_order_lines(order_lines)

        origins = set(self.invoice_line_ids.mapped(link).order_id.mapped("name"))
        self.invoice_origin = ",".join(origins)

        if self.company_id != order.company_id:
            self.company_id = order.company_id

        self[order_field] = False

    def _action_order_line_matching(self, name, res_model, list_view_xmlid):
        self.check_singleton()
        return {
            "type": "ir.actions.act_window",
            "name": name,
            "res_model": res_model,
            "domain": [
                (
                    "partner_id",
                    "in",
                    (self.partner_id | self.partner_id.commercial_partner_id).ids,
                ),
                ("company_id", "in", self.env.companies.ids),
                ("company_id", "child_of", self.company_id.ids),
                ("account_move_id", "in", [self.id, False]),
            ],
            "views": [(self.env.ref(list_view_xmlid).id, "list")],
        }

    def _action_view_source_orders(self, order_model, action_xmlid, form_xmlid):
        self.check_singleton()
        source_orders = self._get_source_orders(order_model)
        if not source_orders:
            return {"type": "ir.actions.act_window_close"}
        result = self.env["ir.actions.act_window"]._get_action_dict_by_xml_id(
            action_xmlid
        )
        if len(source_orders) > 1:
            result["domain"] = [("id", "in", source_orders.ids)]
        else:
            result["views"] = [(self.env.ref(form_xmlid).id, "form")]
            result["res_id"] = source_orders.id
        return result

    def _create_order_from_invoice(self, order_model):
        self.check_singleton()
        Order = self.env[order_model]
        if any(not line.product_id for line in self.invoice_line_ids):
            _debug.logic("order_from_move_refused", move=self, reason="line_no_product")
            raise UserError(
                self.env._("Some move lines do not have a product set. Please review.")
            )

        existing = Order.search(
            [
                ("partner_id", "=", self.commercial_partner_id.id),
                ("company_id", "=", self.company_id.id),
                ("origin", "=", self.name),
            ],
            limit=2,
        )
        if len(existing) > 1:
            _debug.logic(
                "order_from_move_refused",
                move=self,
                reason="ambiguous_origin",
                orders=existing,
            )
            raise UserError(
                self.env._(
                    "More than one %(orders)s has this document as its origin."
                    " Please review.",
                    orders=Order._description,
                )
            )
        if existing:
            _debug.logic("order_from_move_reused", move=self, order=existing)
            return existing

        order = Order.create(self._prepare_order_vals_from_invoice(order_model))
        line_vals_by_move_line = self._prepare_order_line_vals_from_invoice(order)
        order_lines = self.env[order._get_line_model()].create(
            list(line_vals_by_move_line.values())
        )
        link = self._get_order_line_link_field(order_model)
        for move_line_id, order_line in zip(
            line_vals_by_move_line, order_lines, strict=True
        ):
            self.env["account.move.line"].browse(move_line_id)[link] = order_line
        _debug.lifecycle("order_created_from_move", move=self, order=order)
        return order

    def _prepare_order_vals_from_invoice(self, order_model):
        self.check_singleton()
        return {
            "company_id": self.company_id.id,
            "currency_id": self.currency_id.id,
            "partner_id": self.commercial_partner_id.id,
            "date_order": self.invoice_date,
            "fiscal_position_id": (
                self.fiscal_position_id
                or self.env["account.fiscal.position"]._get_fiscal_position(
                    self.commercial_partner_id,
                )
            ).id,
            "payment_term_id": self.invoice_payment_term_id.id,
            "origin": self.name,
            "invoice_state": "done",
        }

    def _prepare_order_line_vals_from_invoice(self, order):
        self.check_singleton()
        taxes_field = direction_of(order).product_taxes_field
        company_domain = self.env["account.tax"]._check_company_domain(self.company_id)
        line_vals = {}
        for line in self.invoice_line_ids.filtered(
            lambda ln: ln.display_type == "product",
        ):
            taxes = order.fiscal_position_id.map_tax(
                line.product_id.sudo()[taxes_field]
            )
            if taxes:
                taxes = taxes.filtered_domain(company_domain)
            line_vals[line.id] = {
                "order_id": order.id,
                "product_id": line.product_id.id,
                "name": (
                    f"[{line.product_id.default_code}] {line.name}"
                    if line.product_id.default_code
                    else line.name
                ),
                "product_qty": line.quantity,
                "product_uom_id": line.product_uom_id.id,
                "price_unit": line.price_unit,
                "tax_ids": [Command.set(taxes.ids)],
                "analytic_distribution": line.analytic_distribution,
            }
        return line_vals
