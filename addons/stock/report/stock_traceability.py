from collections import deque

from markupsafe import Markup

from odoo import _, api, models
from odoo.tools import format_datetime


class StockTraceabilityReport(models.TransientModel):
    _name = "stock.traceability.report"
    _description = "Traceability Report"

    @api.model
    def _get_move_lines(self, move_lines, line_id=None):
        """Walk the upstream move-line chain feeding ``move_lines``.

        ``line_id`` selects how deep to traverse:

        * ``None`` -- follow the chain to its end. Used only to test whether
          *any* upstream exists (see :meth:`_has_upstream_move_lines`, which is
          the cheaper way to ask that question).
        * anything else -- return only the first upstream generation. This is
          the lazy, one-level unfold the web client performs: each returned
          line is itself unfoldable to go one level deeper.

        ``move_lines`` may be a single record or a recordset; the seed is
        excluded from the result.
        """
        lines_seen = move_lines
        lines_todo = deque(move_lines)
        while lines_todo:
            move_line = lines_todo.popleft()
            # made-to-order: follow the explicit move link
            if move_line.move_id.move_orig_ids:
                lines = (
                    move_line.move_id.move_orig_ids.move_line_ids.filtered(
                        lambda m, lot=move_line.lot_id: (
                            m.lot_id == lot and m.state == "done"
                        )
                    )
                    - lines_seen
                )
            # made-to-stock: rediscover the line that fed this location
            elif move_line.location_id.usage in ("internal", "transit"):
                lines = self.env["stock.move.line"].search(
                    [
                        ("product_id", "=", move_line.product_id.id),
                        ("lot_id", "=", move_line.lot_id.id),
                        ("location_dest_id", "=", move_line.location_id.id),
                        ("id", "not in", lines_seen.ids),
                        ("date", "<=", move_line.date),
                        ("state", "=", "done"),
                    ]
                )
            else:
                continue
            if line_id is None:
                lines_todo.extend(lines)
            lines_seen |= lines
        return lines_seen - move_lines

    @api.model
    def _has_upstream_move_lines(self, move_line):
        """Whether ``move_line`` has any traceable upstream line.

        Equivalent to ``bool(self._get_move_lines(move_line))`` but stops at the
        first hit instead of materialising the whole chain -- this only feeds
        the ``unfoldable`` flag, so a full walk per rendered line is wasteful.
        """
        if move_line.move_id.move_orig_ids:
            return bool(
                move_line.move_id.move_orig_ids.move_line_ids.filtered(
                    lambda m: m.lot_id == move_line.lot_id and m.state == "done"
                )
                - move_line
            )
        if move_line.location_id.usage in ("internal", "transit"):
            return bool(
                self.env["stock.move.line"].search(
                    [
                        ("product_id", "=", move_line.product_id.id),
                        ("lot_id", "=", move_line.lot_id.id),
                        ("location_dest_id", "=", move_line.location_id.id),
                        ("id", "!=", move_line.id),
                        ("date", "<=", move_line.date),
                        ("state", "=", "done"),
                    ],
                    limit=1,
                )
            )
        return False

    @api.model
    def get_lines(self, line_id=False, **kw):
        context = self.env.context
        model = kw.get("model_name") or context.get("model")
        rec_id = kw.get("model_id") or context.get("active_id")
        level = kw.get("level") or 1
        move_lines = self.env["stock.move.line"]
        if rec_id and model == "stock.lot":
            move_lines = move_lines.search(
                [
                    ("lot_id", "=", context.get("lot_name") or rec_id),
                    ("state", "=", "done"),
                ]
            )
        elif rec_id and model == "stock.move.line" and context.get("lot_name"):
            is_used = self._get_linked_move_lines(self.env[model].browse(rec_id))[1]
            if is_used:
                move_lines = is_used
        elif rec_id and model in ("stock.picking", "mrp.production"):
            record = self.env[model].browse(rec_id)
            if model == "stock.picking":
                move_lines = record.move_ids.move_line_ids.filtered(
                    lambda m: m.lot_id and m.state == "done"
                )
            else:
                move_lines = record.move_finished_ids.move_line_ids.filtered(
                    lambda m: m.state == "done"
                )
        vals = self._lines(
            line_id, model_id=rec_id, model=model, level=level, move_lines=move_lines
        )
        vals.sort(key=lambda v: v["date"], reverse=True)
        return self._final_vals_to_lines(vals)

    @api.model
    def _get_reference(self, move_line):
        res_model = ""
        res_id = False
        ref = ""
        picking_id = move_line.picking_id or move_line.move_id.picking_id
        if picking_id:
            res_model = "stock.picking"
            res_id = picking_id.id
            ref = picking_id.name
        elif move_line.move_id.is_inventory:
            res_model = "stock.move"
            res_id = move_line.move_id.id
            ref = _("Inventory Adjustment")
        elif (
            move_line.move_id.location_dest_usage == "inventory"
            and move_line.move_id.scrap_id
        ):
            res_model = "stock.scrap"
            res_id = move_line.move_id.scrap_id.id
            ref = move_line.move_id.scrap_id.name
        return res_model, res_id, ref

    @api.model
    def _quantity_to_str(self, from_uom, to_uom, qty):
        """workaround to apply the float rounding logic of t-esc on data prepared server side"""
        qty = from_uom._compute_quantity_report(qty, to_uom, rounding_method="HALF-UP")
        return self.env["ir.qweb.field.float"].value_to_html(
            qty, {"decimal_precision": "Product Unit"}
        )

    @api.model
    def _get_usage(self, move_line):
        source_internal = move_line.location_id.usage == "internal"
        dest_internal = move_line.location_dest_id.usage == "internal"
        if source_internal and dest_internal:
            return "internal"
        if dest_internal:
            return "in"
        return "out"

    @api.model
    def _get_partner_names(self, move_line):
        """Return partner name instead of source or destination location based on
        whether the product is incoming or outgoing.
        """
        source_name = move_line.location_id.display_name
        destination_name = move_line.location_dest_id.display_name
        partner_name = move_line.picking_partner_id.name
        picking_code = move_line.picking_id.picking_type_code
        if picking_code == "incoming":
            return partner_name, destination_name
        if picking_code == "outgoing":
            return source_name, partner_name
        return source_name, destination_name

    @api.model
    def _make_dict_move(self, level, parent_id, move_line, unfoldable=False):
        res_model, res_id, ref = self._get_reference(move_line)
        is_used = self._get_linked_move_lines(move_line)[1]
        location_source, location_destination = self._get_partner_names(move_line)
        return {
            "level": level,
            "unfoldable": unfoldable,
            "date": move_line.move_id.date,
            "parent_id": parent_id,
            "is_used": bool(is_used),
            "usage": self._get_usage(move_line),
            "model_id": move_line.id,
            "model": "stock.move.line",
            "product_id": move_line.product_id.display_name,
            "product_qty_uom": "%s %s"
            % (
                self._quantity_to_str(
                    move_line.product_uom_id,
                    move_line.product_id.uom_id,
                    move_line.quantity,
                ),
                move_line.product_id.uom_id.name,
            ),
            "lot_name": move_line.lot_id.name,
            "lot_id": move_line.lot_id.id,
            "location_source": location_source,
            "location_destination": location_destination,
            "partner_id": move_line.picking_partner_id.id,
            "picking_type_code": move_line.picking_id.picking_type_code,
            "reference_id": ref,
            "res_id": res_id,
            "res_model": res_model,
        }

    @api.model
    def _final_vals_to_lines(self, final_vals):
        """Turn the intermediate move dicts into client rows.

        Row ``id`` is a per-response sequence (1..N): the web client only uses
        it as an OWL ``t-key`` within a sibling group and hands it straight back
        as ``line_id`` on unfold, so it only has to be truthy and locally
        unique -- not globally unique across requests.
        """
        return [
            {
                "id": counter,
                "model": data["model"],
                "model_id": data["model_id"],
                "parent_id": data["parent_id"],
                "usage": data["usage"],
                "is_used": data["is_used"],
                "lot_name": data["lot_name"],
                "lot_id": data["lot_id"],
                "reference": data["reference_id"],
                "location_source": data["location_source"],
                "location_destination": data["location_destination"],
                "partner_id": data["partner_id"],
                "picking_type_code": data["picking_type_code"],
                "res_id": data["res_id"],
                "res_model": data["res_model"],
                "columns": [
                    data["reference_id"],
                    data["product_id"],
                    format_datetime(self.env, data["date"], tz=False, dt_format=False),
                    data["lot_name"],
                    data["location_source"],
                    data["location_destination"],
                    data["product_qty_uom"],
                ],
                "level": data["level"],
                "unfoldable": data["unfoldable"],
            }
            for counter, data in enumerate(final_vals, start=1)
        ]

    @api.model
    def _get_linked_move_lines(self, move_line):
        """Return ``(produced_or_consumed_lines, is_used)`` for this operation.

        Base stock has no produce/consume concept; ``mrp`` and ``repair``
        override this to inject their linkage.
        """
        return False, False

    @api.model
    def _lines(
        self, line_id=False, model_id=False, model=False, level=0, move_lines=None
    ):
        final_vals = []
        lines = move_lines or self.env["stock.move.line"]
        if model and line_id:
            move_line = self.env[model].browse(model_id)
            linked_lines = self._get_linked_move_lines(move_line)[0]
            if linked_lines:
                lines = linked_lines
            else:
                # not produced/consumed by an override (e.g. MRP): trace the raw move chain
                lines = self._get_move_lines(move_line, line_id=line_id)
        for line in lines:
            unfoldable = bool(
                line.consume_line_ids
                or (
                    model != "stock.lot"
                    and line.lot_id
                    and self._has_upstream_move_lines(line)
                )
            )
            final_vals.append(
                self._make_dict_move(
                    level, parent_id=line_id, move_line=line, unfoldable=unfoldable
                )
            )
        return final_vals

    def get_pdf_lines(self, line_data=None):
        final_vals = []
        for line in line_data or []:
            move_line = self.env[line["model_name"]].browse(line["model_id"])
            final_vals.append(
                self._make_dict_move(
                    line["level"],
                    parent_id=line["id"],
                    move_line=move_line,
                    unfoldable=line.get("unfoldable", False),
                )
            )
        return self._final_vals_to_lines(final_vals)

    def get_pdf(self, line_data=None):
        lines = self.with_context(print_mode=True).get_pdf_lines(line_data or [])
        base_url = self.env["ir.config_parameter"].sudo().get_param("web.base.url")
        rcontext = {
            "mode": "print",
            "base_url": base_url,
        }

        context = dict(self.env.context)
        if context.get("active_id") and context.get("active_model"):
            rcontext["reference"] = (
                self.env[context["active_model"]]
                .browse(int(context["active_id"]))
                .display_name
            )

        body = (
            self.env["ir.ui.view"]
            .with_context(context)
            ._render_template(
                "stock.report_stock_inventory_print",
                values=dict(rcontext, lines=lines, report=self, context=self),
            )
        )

        header = self.env["ir.actions.report"]._render_template(
            "web.internal_layout", values=rcontext
        )
        header = self.env["ir.actions.report"]._render_template(
            "web.minimal_layout",
            values=dict(rcontext, subst=True, body=Markup(header.decode())),
        )

        IrReport = self.env["ir.actions.report"]
        body_with_header = IrReport._inject_header_footer_html(
            body, header=header.decode()
        )
        return IrReport._render_html_to_pdf(
            [body_with_header],
            landscape=True,
            specific_paperformat_args={
                "data-report-margin-top": 30,
            },
        )

    @api.model
    def get_main_lines(self, given_context=None):
        report = self.search([("create_uid", "=", self.env.uid)], limit=1)
        if not report:
            report = self.create({})
        return report.with_context(given_context or {}).get_lines()
