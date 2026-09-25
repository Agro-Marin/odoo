import difflib
import logging
import time

from markupsafe import Markup

from odoo import api, fields, models
from odoo.fields import Command
from odoo.tools import frozendict

from odoo.addons.purchase import const

_logger = logging.getLogger(__name__)


class AccountMove(models.Model):
    _inherit = "account.move"
    _access_anchors = frozendict(
        {
            "owner": models.Anchor("invoice_user_id", shared=True),
        }
    )

    purchase_vendor_bill_id = fields.Many2one(
        comodel_name="purchase.bill.match",
        string="Auto-complete",
        store=False,
        readonly=False,
        help="Auto-complete from a previous bill, refund, or purchase order.",
    )
    purchase_id = fields.Many2one(
        comodel_name="purchase.order",
        string="Purchase Order",
        store=False,
        readonly=False,
        help="Auto-complete from a past purchase order.",
    )
    purchase_order_count = fields.Integer(compute="_compute_purchase_order_count")
    purchase_order_name = fields.Char(compute="_compute_purchase_order_name")
    is_purchase_matched = fields.Boolean(
        compute="_compute_is_purchase_matched",
        help="0: PO not required or partially linked. 1: All lines linked",
    )
    purchase_warning_text = fields.Text(
        string="Purchase Warning",
        compute="_compute_purchase_warning_text",
        depends_context=("uid",),
        help="Internal warning for the partner or the products as set by the user.",
    )

    @api.model_create_multi
    def create(self, vals_list):
        moves = super().create(vals_list)
        for move in moves:
            if move.reversed_entry_id:
                continue
            purchases = move.line_ids.purchase_line_ids.order_id
            if not purchases:
                continue
            refs = [purchase._get_html_link() for purchase in purchases]
            message = self.env._("This vendor bill has been created from: ") + Markup(
                ","
            ).join(
                refs,
            )
            move.message_post(body=message)
        return moves

    def write(self, vals):
        if not ({"line_ids", "invoice_line_ids"} & vals.keys()):
            return super().write(vals)
        old_purchases = [
            move.mapped("line_ids.purchase_line_ids.order_id") for move in self
        ]
        res = super().write(vals)
        for i, move in enumerate(self):
            if move.reversed_entry_id:
                continue
            new_purchases = move.mapped("line_ids.purchase_line_ids.order_id")
            if not new_purchases:
                continue
            diff_purchases = new_purchases - old_purchases[i]
            if diff_purchases:
                refs = [purchase._get_html_link() for purchase in diff_purchases]
                message = self.env._(
                    "This vendor bill has been modified from: "
                ) + Markup(
                    ",",
                ).join(refs)
                move.message_post(body=message)
        return res

    @api.depends(
        "move_type", "partner_id", "line_ids.purchase_line_ids.order_id.user_id"
    )
    def _compute_invoice_user_id(self):
        super()._compute_invoice_user_id()
        for move in self:
            if move.is_purchase_document(include_receipts=True):
                if not move.invoice_user_id or move.invoice_user_id == self.env.user:
                    purchase_orders = move.line_ids.purchase_line_ids.order_id
                    move.invoice_user_id = (
                        purchase_orders[:1].user_id
                        or move.partner_id.user_purchase_id
                        or move.partner_id.commercial_partner_id.user_purchase_id
                        or self.env.user
                    )

    @api.depends("line_ids.purchase_line_ids")
    def _compute_is_purchase_matched(self):
        for move in self:
            move.is_purchase_matched = move._is_matched_to_orders("purchase.order")

    @api.depends("line_ids.purchase_line_ids")
    def _compute_purchase_order_count(self):
        for move in self:
            move.purchase_order_count = len(move._get_source_orders("purchase.order"))

    @api.depends(
        "purchase_order_count",
        "invoice_line_ids.purchase_line_ids.order_id.display_name",
    )
    def _compute_purchase_order_name(self):
        for move in self:
            move.purchase_order_name = move._get_source_order_name("purchase.order")

    @api.depends(
        "partner_id.name",
        "partner_id.purchase_warn_msg",
        "partner_id.parent_id.name",
        "partner_id.parent_id.purchase_warn_msg",
        "invoice_line_ids.product_id.purchase_line_warn_msg",
        "invoice_line_ids.product_id.display_name",
    )
    def _compute_purchase_warning_text(self):
        if not self.env.user.has_group("purchase.group_warning_purchase"):
            self.purchase_warning_text = ""
            return
        for move in self:
            move.purchase_warning_text = move._get_order_warning_text(
                "in_invoice", "purchase_warn_msg", "purchase_line_warn_msg"
            )

    @api.onchange("purchase_vendor_bill_id", "purchase_id")
    def _onchange_purchase_auto_complete(self):
        self._auto_complete_from_order("purchase_vendor_bill_id", "purchase_id")

    @api.onchange("partner_id", "company_id")
    def _onchange_partner_id(self):
        res = super()._onchange_partner_id()

        currency_id = (
            self.partner_id.property_purchase_currency_id
            or self.env["res.currency"].browse(
                self.env.context.get("default_currency_id"),
            )
            or self.currency_id
        )

        if (
            self.partner_id
            and self.move_type in ["in_invoice", "in_refund"]
            and self.currency_id != currency_id
        ):
            if not self.env.context.get("default_journal_id"):
                journal_domain = [
                    *self.env["account.journal"]._check_company_domain(self.company_id),
                    ("type", "=", "purchase"),
                    ("currency_id", "=", currency_id.id),
                ]
                default_journal_id = self.env["account.journal"].search(
                    journal_domain,
                    limit=1,
                )
                if default_journal_id:
                    self.journal_id = default_journal_id

            self.currency_id = currency_id

        return res

    def action_purchase_matching(self):
        return self._action_order_line_matching(
            self.env._("Purchase Matching"),
            "purchase.bill.line.match",
            "purchase.purchase_bill_line_match_list",
        )

    def action_view_source_purchase_orders(self):
        return self._action_view_source_orders(
            "purchase.order",
            "purchase.action_purchase_order_2",
            "purchase.view_purchase_order_form",
        )

    def create_purchase_order(self):
        return self._create_order_from_invoice("purchase.order")

    def _find_and_set_purchase_orders(
        self,
        po_references,
        partner_id,
        amount_total,
        from_ocr=False,
        timeout=10,
    ):
        self.check_singleton()

        method, matched_po_lines, matched_inv_lines = self._match_purchase_orders(
            po_references,
            partner_id,
            amount_total,
            from_ocr,
            timeout,
        )

        if method in ("total_match", "po_match"):
            self._set_purchase_orders(matched_po_lines.order_id, force_write=True)
        elif method == "subset_total_match":
            self._set_purchase_orders(matched_po_lines.order_id, force_write=False)

            with self._get_edi_creation() as invoice:
                unmatched_lines = invoice.invoice_line_ids.filtered(
                    lambda l: (
                        l.purchase_line_ids
                        and l.purchase_line_ids not in matched_po_lines
                    ),
                )
                invoice.invoice_line_ids = [
                    Command.update(line.id, {"quantity": 0}) for line in unmatched_lines
                ]
        elif method == "subset_match":
            self._set_purchase_orders(matched_po_lines.order_id, force_write=False)

            with self._get_edi_creation() as invoice:
                unmatched_lines = invoice.invoice_line_ids.filtered(
                    lambda l: (
                        l.purchase_line_ids
                        and l.purchase_line_ids not in matched_po_lines
                    ),
                )
                invoice.invoice_line_ids = [
                    Command.delete(line.id) for line in unmatched_lines
                ]

                inv_and_po_lines = list(
                    map(
                        lambda line: (
                            invoice.invoice_line_ids.filtered(
                                lambda l: line[0] in l.purchase_line_ids.ids,
                            ),
                            invoice.invoice_line_ids.filtered(lambda l: l in line[1]),
                        ),
                        matched_inv_lines,
                    ),
                )
                invoice.invoice_line_ids = [
                    Command.update(
                        po_line.id,
                        {
                            "quantity": inv_line.product_uom_id._get_quantity_in_unit(
                                inv_line.quantity, po_line.product_uom_id
                            ),
                            "tax_ids": inv_line.tax_ids,
                        },
                    )
                    for po_line, inv_line in inv_and_po_lines
                ]
                invoice.invoice_line_ids = [
                    Command.delete(inv_line.id) for dummy, inv_line in inv_and_po_lines
                ]

                unmatched_lines = invoice.invoice_line_ids.filtered(
                    lambda l: not l.purchase_line_ids,
                )
                if len(unmatched_lines) > 0:
                    invoice.invoice_line_ids = [
                        Command.create(
                            {
                                "display_type": "line_section",
                                "name": self.env._("From Electronic Document"),
                                "sequence": -1,
                            },
                        ),
                    ]

        if not any(line.purchase_line_ids.order_id for line in self.line_ids):
            self.invoice_origin = False

    def _get_matching_po_and_inv_lines(self, po_lines, inv_lines, timeout):
        invoice_lines = sorted(
            inv_lines,
            key=lambda line: (line.price_unit, line.quantity),
            reverse=True,
        )
        purchase_lines = sorted(
            po_lines,
            key=lambda line: (line.price_unit, line.product_qty - line.qty_invoiced),
            reverse=True,
        )
        matched_po_lines = []
        matched_inv_lines = []
        try:
            start_time = time.time()
            for invoice_line in invoice_lines:
                if not purchase_lines:
                    break
                purchase_line_candidates = {}
                for purchase_line in purchase_lines:
                    if time.time() - start_time > timeout:
                        raise TimeoutError

                    if purchase_line.price_unit < invoice_line.price_unit:
                        break

                    if (
                        invoice_line.price_unit == purchase_line.price_unit
                        and invoice_line.quantity
                        <= purchase_line.product_qty - purchase_line.qty_invoiced
                    ):
                        purchase_line_candidates[purchase_line] = (
                            difflib.SequenceMatcher(
                                None,
                                invoice_line.name,
                                purchase_line.name,
                            ).ratio()
                        )

                if len(purchase_line_candidates) > 0:
                    purchase_line_match = max(
                        purchase_line_candidates,
                        key=purchase_line_candidates.get,
                    )
                    if purchase_line_match:
                        purchase_lines.remove(purchase_line_match)
                        matched_po_lines.append(purchase_line_match)
                        matched_inv_lines.append((purchase_line_match.id, invoice_line))

            return (matched_po_lines, matched_inv_lines)
        except TimeoutError:
            _logger.warning("Timed out during search of matching purchase order lines")
            return ([], [])

    def _get_matching_subset_po_lines(self, po_lines_with_amount, goal_total, timeout):
        def get_matching_subsets(lines, goal):
            if time.time() - start_time > timeout:
                raise TimeoutError
            solutions = []
            for i, line in enumerate(lines):
                if line["amount_to_invoice"] < goal - const.BILLING_MATCH_TOLERANCE:
                    sub_solutions = get_matching_subsets(
                        lines[i + 1 :],
                        goal - line["amount_to_invoice"],
                    )
                    solutions.extend(
                        (line["line"], *solution) for solution in sub_solutions
                    )
                elif (
                    goal - const.BILLING_MATCH_TOLERANCE
                    <= line["amount_to_invoice"]
                    <= goal + const.BILLING_MATCH_TOLERANCE
                ):
                    solutions.append([line["line"]])
                if len(solutions) > 1:
                    return []
            return solutions

        start_time = time.time()
        try:
            subsets = get_matching_subsets(
                sorted(
                    po_lines_with_amount,
                    key=lambda line: line["amount_to_invoice"],
                    reverse=True,
                ),
                goal_total,
            )
            return subsets[0] if subsets else []
        except TimeoutError:
            _logger.warning(
                "Timed out during search of a matching subset of purchase order lines",
            )
            return []

    def _match_purchase_orders(
        self,
        po_references,
        partner_id,
        amount_total,
        from_ocr,
        timeout,
    ):
        common_domain = [
            ("company_id", "=", self.company_id.id),
            ("state", "=", "done"),
            ("invoice_state", "in", ("to do", "no", "partial")),
        ]

        matching_purchase_orders = self.env["purchase.order"]

        if po_references and amount_total:
            matching_purchase_orders |= self.env["purchase.order"].search(
                common_domain + [("name", "in", po_references)],
            )

            if not matching_purchase_orders:
                matching_purchase_orders |= self.env["purchase.order"].search(
                    common_domain + [("partner_ref", "in", po_references)],
                )

            if matching_purchase_orders:
                po_lines = [
                    line
                    for line in matching_purchase_orders.line_ids
                    if line.product_qty
                ]
                po_lines_with_amount = [
                    {
                        "line": line,
                        "amount_to_invoice": max(
                            0.0, 1 - line.qty_invoiced / line.product_qty
                        )
                        * line.price_total,
                    }
                    for line in po_lines
                ]

                if (
                    amount_total - const.BILLING_MATCH_TOLERANCE
                    < sum(line["amount_to_invoice"] for line in po_lines_with_amount)
                    < amount_total + const.BILLING_MATCH_TOLERANCE
                ):
                    return "total_match", matching_purchase_orders.line_ids, None

                if from_ocr:
                    matching_po_lines = self._get_matching_subset_po_lines(
                        po_lines_with_amount,
                        amount_total,
                        timeout,
                    )
                    if matching_po_lines:
                        return (
                            "subset_total_match",
                            self.env["purchase.order.line"].union(*matching_po_lines),
                            None,
                        )
                    return "po_match", matching_purchase_orders.line_ids, None

                matching_po_lines, matching_inv_lines = (
                    self._get_matching_po_and_inv_lines(
                        po_lines,
                        self.invoice_line_ids,
                        timeout,
                    )
                )

                if matching_po_lines:
                    return (
                        "subset_match",
                        self.env["purchase.order.line"].union(*matching_po_lines),
                        matching_inv_lines,
                    )

        if partner_id and amount_total:
            purchase_id_domain = common_domain + [
                ("partner_id", "child_of", [partner_id]),
                ("amount_total", ">=", amount_total - const.BILLING_MATCH_TOLERANCE),
                ("amount_total", "<=", amount_total + const.BILLING_MATCH_TOLERANCE),
            ]
            matching_purchase_orders = self.env["purchase.order"].search(
                purchase_id_domain,
            )
            if len(matching_purchase_orders) == 1:
                return "total_match", matching_purchase_orders.line_ids, None

        return ("no_match", matching_purchase_orders.line_ids, None)

    def _set_purchase_orders(self, purchase_orders, force_write=True):
        with self.env.cr.savepoint():
            with self._get_edi_creation() as invoice:
                if force_write and invoice.line_ids:
                    invoice.invoice_line_ids = [Command.clear()]
                for purchase_order in purchase_orders:
                    invoice.invoice_line_ids = [
                        Command.create(
                            {
                                "display_type": "line_section",
                                "name": self.env._("From %s", purchase_order.name),
                            },
                        ),
                    ]
                    invoice.purchase_id = purchase_order
                    invoice._onchange_purchase_auto_complete()

    def _prepare_order_vals_from_invoice(self, order_model):
        values = super()._prepare_order_vals_from_invoice(order_model)
        if order_model == "purchase.order":
            values["dest_address_id"] = False
        return values

    def _prepare_order_line_vals_from_invoice(self, order):
        line_vals = super()._prepare_order_line_vals_from_invoice(order)
        if order._name == "purchase.order":
            for vals in line_vals.values():
                vals["date_commitment"] = order.date_order
        return line_vals
