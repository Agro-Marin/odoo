from collections import defaultdict

from odoo import _, api, models
from odoo.tools import format_date


class ReportStockReport_Reception(models.AbstractModel):
    _name = "report.stock.report_reception"
    _description = "Stock Reception Report"

    # ------------------------------------------------------------------
    # Report values
    # ------------------------------------------------------------------

    @api.model
    def get_report_data(self, docids, data):
        """Entry point for the interactive (OWL) report: same values as
        `_get_report_values` but with recordsets flattened to JSON-friendly
        primitives for the RPC payload."""
        report_values = self._get_report_values(docids, data)
        sources_to_lines = report_values.get("sources_to_lines", {})
        report_values["docs"] = self._format_html_docs(report_values.get("docs"))
        report_values["sources_info"] = self._format_html_sources_info(sources_to_lines)
        report_values["sources_to_lines"] = self._format_html_sources_to_lines(
            sources_to_lines
        )
        report_values["sources_to_formatted_scheduled_date"] = (
            self._format_html_sources_to_date(
                report_values.get("sources_to_formatted_scheduled_date", {})
            )
        )
        report_values["show_uom"] = self.env.user.has_group("uom.group_uom")
        return report_values

    @api.model
    def _get_report_values(self, docids, data=None):
        """This report is flexibly designed to work with both individual and batch pickings."""
        docs, reason = self._get_validated_docs(docids)
        if not docs:
            return {"docs": False, "reason": reason}

        doc_states = docs.mapped("state")
        moves = self._get_moves(docs)

        # Classify every incoming move by how it can be presented.
        qty_draft, qty_to_assign, total_assigned = self._classify_incoming_moves(moves)

        # Candidate outgoing moves that these incoming quantities could cover.
        outs = self._search_candidate_outs(docs, doc_states, qty_to_assign, qty_draft)

        sources_to_lines = self._match_outs_to_incoming(
            outs, doc_states, qty_to_assign, qty_draft
        )
        self._add_assigned_lines(sources_to_lines, total_assigned)

        # dates aren't auto-formatted when printed in report :(
        sources_to_formatted_scheduled_date = {
            source: self._get_formatted_scheduled_date(source[0])
            for source in sources_to_lines
        }

        return {
            "data": data,
            "doc_ids": docids,
            "doc_model": self._get_doc_model(),
            "sources_to_lines": sources_to_lines,
            "precision": self.env["decimal.precision"].precision_get("Product Unit"),
            "docs": docs,
            "sources_to_formatted_scheduled_date": sources_to_formatted_scheduled_date,
        }

    def _get_validated_docs(self, docids):
        """Return `(docs, reason)`. `docs` is empty (and `reason` set) for the
        unsupported cases the report cannot render."""
        docs = self._get_docs(docids)
        doc_types = self._get_doc_types()
        if not docs:
            return docs, _("No %s selected or a delivery order selected", doc_types)
        doc_states = docs.mapped("state")
        if "done" in doc_states and len(set(doc_states)) > 1:
            return docs.browse(), _(
                "This report cannot be used for done and not done %s at the same time",
                doc_types,
            )
        return docs, None

    def _classify_incoming_moves(self, moves):
        """Bucket incoming `moves` by how their quantity should appear in the
        report:

        * `qty_draft`      product -> qty from draft moves (shown, not assignable)
        * `qty_to_assign`  product -> FIFO list of `(qty, move)` still to assign
        * `total_assigned` product -> `[already_assigned_qty, [move ids]]`
        """
        qty_draft = defaultdict(float)
        qty_to_assign = defaultdict(list)
        total_assigned = defaultdict(lambda: [0.0, []])

        # Pool of quantities already reserved through destination moves, drawn
        # down greedily below so batch pickings don't double-count them.
        assigned_pool = defaultdict(float)
        for assigned in moves.move_dest_ids:
            assigned_pool[assigned.product_id] += assigned.product_qty

        for move in moves:
            product = move.product_id
            move_quantity = self._get_move_quantity(move)
            qty_already_assigned = 0
            if move.move_dest_ids:
                qty_already_assigned = min(assigned_pool[product], move_quantity)
                assigned_pool[product] -= qty_already_assigned
            if qty_already_assigned:
                total_assigned[product][0] += qty_already_assigned
                total_assigned[product][1].append(move.id)
            remaining = move_quantity - qty_already_assigned
            if not product.uom_id.is_zero(remaining):
                if move.state == "draft":
                    qty_draft[product] += remaining
                else:
                    qty_to_assign[product].append((remaining, move))
        return qty_draft, qty_to_assign, total_assigned

    def _search_candidate_outs(self, docs, doc_states, qty_to_assign, qty_draft):
        """Outgoing moves (not already chained, non-mto, same warehouse) that
        could consume the incoming quantities."""
        # only match for non-mto moves in same warehouse
        warehouse = docs[0].picking_type_id.warehouse_id
        wh_location_ids = self.env["stock.location"]._search(
            [
                ("id", "child_of", warehouse.view_location_id.id),
                ("usage", "!=", "supplier"),
            ]
        )

        allowed_states = ["confirmed", "partially_available", "waiting"]
        if "done" in doc_states:
            # only done moves are allowed to be assigned to already reserved moves
            allowed_states.append("assigned")

        product_ids = [product.id for product in {*qty_to_assign, *qty_draft}]
        return self.env["stock.move"].search(
            [
                ("state", "in", allowed_states),
                ("product_qty", ">", 0),
                ("location_id", "in", wh_location_ids),
                ("move_orig_ids", "=", False),
                ("product_id", "in", product_ids),
            ]
            + self._get_extra_domain(docs),
            order="date_reservation, priority desc, date, id",
        )

    def _match_outs_to_incoming(self, outs, doc_states, qty_to_assign, qty_draft):
        """Build `sources_to_lines`: for each outgoing move, draw from the
        assignable incoming queue and, for any shortfall, from expected drafts."""
        products_to_outs = defaultdict(list)
        for out in outs:
            products_to_outs[out.product_id].append(out)

        sources_to_lines = defaultdict(list)  # group by source to print together
        for product, product_outs in products_to_outs.items():
            product_uom_id = product.uom_id
            assign_queue = qty_to_assign[product]
            for out in product_outs:
                source = self._get_report_source(out)
                if not source:
                    continue

                qty_to_reserve = out.product_qty
                if "done" not in doc_states and out.state == "partially_available":
                    qty_to_reserve -= out.product_uom_id._compute_quantity(
                        out.quantity, product_uom_id
                    )

                quantity, moves_in_ids = self._consume_from_queue(
                    assign_queue, qty_to_reserve, product_uom_id
                )
                if not product_uom_id.is_zero(quantity):
                    sources_to_lines[source].append(
                        self._prepare_report_line(
                            quantity,
                            product,
                            out,
                            source[0],
                            move_ins=self.env["stock.move"].browse(moves_in_ids),
                        )
                    )

                # draft qtys can be shown but not assigned
                qty_expected = qty_draft.get(product, 0)
                if product_uom_id.compare(
                    qty_to_reserve, quantity
                ) > 0 and not product_uom_id.is_zero(qty_expected):
                    to_expect = min(qty_expected, qty_to_reserve - quantity)
                    sources_to_lines[source].append(
                        self._prepare_report_line(
                            to_expect,
                            product,
                            out,
                            source[0],
                            is_qty_assignable=False,
                        )
                    )
                    qty_draft[product] -= to_expect
        return sources_to_lines

    def _consume_from_queue(self, assign_queue, qty_to_reserve, product_uom_id):
        """Draw up to `qty_to_reserve` from the FIFO `assign_queue` of
        `(qty, move)` entries, mutating it in place (fully-consumed entries are
        popped, a partially-consumed entry keeps its remainder at the front).

        :returns: `(quantity_drawn, [ids of every incoming move drawn from])`
        """
        quantity = 0
        moves_in_ids = []
        while assign_queue and product_uom_id.compare(quantity, qty_to_reserve) < 0:
            move_in_qty, move_in = assign_queue[0]
            moves_in_ids.append(move_in.id)
            if product_uom_id.compare(quantity + move_in_qty, qty_to_reserve) <= 0:
                quantity += move_in_qty
                assign_queue.pop(0)
            else:
                qty_to_add = qty_to_reserve - quantity
                quantity += qty_to_add
                assign_queue[0] = (move_in_qty - qty_to_add, move_in)
                break
        return quantity, moves_in_ids

    def _add_assigned_lines(self, sources_to_lines, total_assigned):
        """Append the already-assigned (chained) lines to `sources_to_lines`."""
        for product, (assigned_qty, move_in_ids) in total_assigned.items():
            moves_in = self.env["stock.move"].browse(move_in_ids)
            for out_move in moves_in.move_dest_ids:
                if out_move.product_id.uom_id.is_zero(assigned_qty):
                    # it is possible there are different in moves linked to the same out moves due to batch
                    # => we guess as to which outs correspond to this report...
                    continue
                source = self._get_report_source(out_move)
                if not source:
                    continue
                qty_assigned = min(assigned_qty, out_move.product_qty)
                sources_to_lines[source].append(
                    self._prepare_report_line(
                        qty_assigned,
                        product,
                        out_move,
                        source[0],
                        is_assigned=True,
                        move_ins=moves_in,
                    )
                )

    def _get_move_quantity(self, move):
        """The move's demand in the product's reference UoM, falling back to the
        reserved quantity when there is no stored demand (e.g. done moves)."""
        return move.product_qty or move.product_uom_id._compute_quantity(
            move.quantity, move.product_id.uom_id, rounding_method="HALF-UP"
        )

    def _prepare_report_line(
        self,
        quantity,
        product,
        move_out,
        source=False,
        is_assigned=False,
        is_qty_assignable=True,
        move_ins=False,
    ):
        return {
            "source": source,
            "product": {"id": product.id, "display_name": product.display_name},
            "uom": product.uom_id.display_name,
            "quantity": quantity,
            "is_qty_assignable": is_qty_assignable,
            "move_out": move_out,
            "is_assigned": is_assigned,
            "move_ins": move_ins.ids if move_ins else False,
        }

    def _get_report_source(self, move):
        # We expect len(source) = 2 when picking + origin [e.g. SO] and len() = 1 otherwise [e.g. MO].
        source = move._get_source_document()
        if not source:
            return False
        if move.picking_id and source != move.picking_id:
            return (move.picking_id, source)
        return (source,)

    def _get_docs(self, docids):
        docids = self.env.context.get("default_picking_ids", docids)
        return self.env["stock.picking"].search(
            [
                ("id", "in", docids),
                ("picking_type_code", "!=", "outgoing"),
                ("state", "!=", "cancel"),
            ]
        )

    def _get_doc_model(self):
        return "stock.picking"

    def _get_doc_types(self):
        return "transfers"

    def _get_moves(self, docs):
        return docs.move_ids.filtered(
            lambda m: m.product_id.is_storable and m.state != "cancel"
        )

    def _get_extra_domain(self, docs):
        return [("picking_id", "not in", docs.ids)]

    def _get_formatted_scheduled_date(self, source):
        """Extendable since different source record types name their "Scheduled Date" field differently."""
        if source._name == "stock.picking":
            return format_date(self.env, source.date_planned)
        return False

    # ------------------------------------------------------------------
    # Assign / unassign
    # ------------------------------------------------------------------

    def action_assign(self, move_ids, qtys, in_ids):
        """Assign picking move(s) [i.e. link] to other moves (i.e. make them MTO)
        :param move_ids ids: the ids of the moves to make MTO
        :param qtys list: the quantities that are being assigned to the move_ids (in same order as move_ids)
        :param in_ids ids: the ids of the moves that are to be assigned to move_ids
        """
        # Drop lines with no incoming moves to link (e.g. the "expected" draft-only
        # lines "Assign all" also sends): nothing to make-to-order, and processing
        # them would wrongly split the out move (and browse(False)[0] would raise).
        assignments = [
            (out_id, qty, ins)
            for out_id, qty, ins in zip(move_ids, qtys, in_ids, strict=False)
            if ins
        ]
        if not assignments:
            return
        out_ids = [out_id for out_id, _qty, _ins in assignments]
        outs = self.env["stock.move"].browse(out_ids)

        # Split outs with only part of demand assigned to avoid reservation problems.
        # Done first so split moves are created in batch; only outs that yield a
        # split are mapped, keeping ids aligned 1:1 with the created moves.
        new_move_vals = []
        split_out_ids = []
        for out, (_out_id, qty_to_link, _ins) in zip(outs, assignments, strict=True):
            if out.product_id.uom_id.compare(out.product_qty, qty_to_link) != 1:
                continue
            split_vals = out._split(out.product_qty - qty_to_link)
            if not split_vals:
                continue
            split_vals[0]["date_reservation"] = out.date_reservation
            new_move_vals += split_vals
            split_out_ids.append(out.id)
        new_outs = self.env["stock.move"].create(new_move_vals)
        # don't do action confirm to avoid creating additional unintentional reservations
        new_outs.write({"state": "confirmed"})
        out_to_new_out = dict(zip(split_out_ids, new_outs, strict=True))

        for out, (_out_id, qty_to_link, ins) in zip(outs, assignments, strict=True):
            potential_ins = self.env["stock.move"].browse(ins)
            if out.id in out_to_new_out:
                new_out = out_to_new_out[out.id]
                if potential_ins[0].state != "done" and out.quantity:
                    # let's assume if 1 of the potential_ins isn't done, then none of them are => we are only assigning the not-reserved
                    # qty and the new move should have all existing reserved quants (i.e. move lines) assigned to it
                    out.move_line_ids.move_id = new_out
                elif potential_ins[0].state == "done" and out.quantity > qty_to_link:
                    # let's assume if 1 of the potential_ins is done, then all of them are => we can link them to already reserved moves, but we
                    # need to make sure the reserved qtys still match the demand amount the move (we're assigning).
                    out.move_line_ids.move_id = new_out
                    assigned_amount = 0
                    matching_locations = potential_ins.location_dest_id
                    for move_line_id in new_out.move_line_ids.sorted(
                        lambda ml, matching_locations=matching_locations: (
                            ml.location_id not in matching_locations
                        )
                    ):
                        if (
                            assigned_amount + move_line_id.quantity_product_uom
                            > qty_to_link
                        ):
                            new_move_line = move_line_id.copy({"quantity": 0})
                            new_move_line.quantity = move_line_id.quantity
                            move_line_id.quantity = (
                                out.product_id.uom_id._compute_quantity(
                                    qty_to_link - assigned_amount,
                                    out.product_uom_id,
                                    rounding_method="HALF-UP",
                                )
                            )
                            new_move_line.quantity -= (
                                out.product_id.uom_id._compute_quantity(
                                    move_line_id.quantity_product_uom,
                                    out.product_uom_id,
                                    rounding_method="HALF-UP",
                                )
                            )
                        move_line_id.move_id = out
                        assigned_amount += move_line_id.quantity_product_uom
                        if (
                            out.product_id.uom_id.compare(assigned_amount, qty_to_link)
                            == 0
                        ):
                            break

            for in_move in reversed(potential_ins):
                move_quantity = self._get_move_quantity(in_move)
                quantity_remaining = move_quantity - sum(
                    in_move.move_dest_ids.mapped("product_qty")
                )
                if (
                    in_move.product_id != out.product_id
                    or in_move.product_id.uom_id.compare(0, quantity_remaining) >= 0
                ):
                    # in move is already completely linked (e.g. during another assign click) => don't count it again
                    potential_ins = potential_ins[1:]
                    continue

                linked_qty = min(move_quantity, qty_to_link)
                in_move.move_dest_ids |= out
                self._action_assign(in_move, out)
                out.procure_method = "make_to_order"
                quantity_remaining -= linked_qty
                qty_to_link -= linked_qty
                if out.product_id.uom_id.is_zero(qty_to_link):
                    break  # qty_to_link is fully satisfied

        (outs | new_outs)._recompute_state()

        # always try to auto-assign to prevent another move from reserving the quant if incoming move is done
        outs._action_assign()

    def action_unassign(self, move_id, qty, in_ids):
        """Unassign moves [i.e. unlink] from a move (i.e. make non-MTO)
        :param move_id id: the id of the move to make non-MTO
        :param qty float: the total quantity that is being unassigned from move_id
        :param in_ids ids: the ids of the moves that are to be unassigned from move_id
        """
        out = self.env["stock.move"].browse(move_id)
        ins = self.env["stock.move"].browse(in_ids)

        amount_unassigned = 0
        for in_move in ins:
            if out.id not in in_move.move_dest_ids.ids:
                continue
            move_quantity = self._get_move_quantity(in_move)
            in_move.move_dest_ids -= out
            self._action_unassign(in_move, out)
            amount_unassigned += min(qty, move_quantity)
            if out.product_id.uom_id.compare(qty, amount_unassigned) <= 0:
                break
        if out.move_orig_ids and out.state != "done":
            # annoying use cases where we need to split the out move:
            # 1. batch reserved + individual picking unreserved
            # 2. moves linked from backorder generation
            total_still_linked = sum(out.move_orig_ids.mapped("product_qty"))
            new_move_vals = out._split(total_still_linked)
            if new_move_vals:
                new_move_vals[0]["procure_method"] = "make_to_order"
                new_move_vals[0]["date_reservation"] = out.date_reservation
                new_out = self.env["stock.move"].create(new_move_vals)
                # don't do action confirm to avoid creating additional unintentional reservations
                new_out.write({"state": "confirmed"})
                out.move_line_ids.move_id = new_out
                (out | new_out)._compute_quantity()
                if new_out.quantity > new_out.product_qty:
                    # extra reserved amount goes to no longer linked out
                    reserved_amount_to_remain = new_out.quantity - new_out.product_qty
                    for move_line_id in new_out.move_line_ids:
                        if reserved_amount_to_remain <= 0:
                            break
                        if (
                            move_line_id.quantity_product_uom
                            > reserved_amount_to_remain
                        ):
                            new_move_line = move_line_id.copy({"quantity": 0})
                            new_move_line.quantity = (
                                out.product_id.uom_id._compute_quantity(
                                    move_line_id.quantity_product_uom
                                    - reserved_amount_to_remain,
                                    move_line_id.product_uom_id,
                                    rounding_method="HALF-UP",
                                )
                            )
                            move_line_id.quantity -= new_move_line.quantity
                            move_line_id.move_id = out
                            break
                        move_line_id.move_id = out
                        reserved_amount_to_remain -= move_line_id.quantity_product_uom
                    (out | new_out)._compute_quantity()
                out.move_orig_ids = False
                new_out._recompute_state()
        out.procure_method = "make_to_stock"
        out._do_unreserve()
        return True

    def _action_assign(self, in_move, out_move):
        """share reference across source documents"""
        in_ref = in_move.reference_ids
        out_ref = out_move.reference_ids
        in_source = in_move._get_source_document()
        out_source = out_move._get_source_document()
        if out_ref and in_source:
            in_source._add_reference(out_ref)
        if in_ref and out_source:
            out_source._add_reference(in_ref)

    def _action_unassign(self, in_move, out_move):
        """remove shared reference across source documents if any"""
        in_ref = in_move.reference_ids
        out_ref = out_move.reference_ids
        in_source = in_move._get_source_document()
        out_source = out_move._get_source_document()
        if out_ref and in_source:
            in_source._remove_reference(out_ref)
        if in_ref and out_source:
            out_source._remove_reference(in_ref)

    # ------------------------------------------------------------------
    # HTML formatting for the interactive (OWL) report
    # ------------------------------------------------------------------

    def _format_html_docs(self, docs):
        """Format docs to be sent in an html request."""
        if not docs:
            return docs
        return [
            {
                "id": doc.id,
                "name": doc.display_name,
                "state": doc.state,
                "display_state": dict(
                    doc._fields["state"]._description_selection(self.env)
                ).get(doc.state),
            }
            for doc in docs
        ]

    def _format_html_sources_to_date(self, sources_to_dates):
        """Format sources_to_formatted_scheduled_date to be sent in an html request."""
        return {str(source): date for (source, date) in sources_to_dates.items()}

    def _format_html_sources_to_lines(self, sources_to_lines):
        """Format sources_to_lines to be sent in an html request, while adding an index for OWL's t-foreach."""
        return {
            str(source): [
                self._format_html_line(line, i) for i, line in enumerate(lines)
            ]
            for source, lines in sources_to_lines.items()
        }

    def _format_html_line(self, line, index):
        """Flatten a report line for the RPC payload: drop the `move_out`
        recordset (only its id is consumed client-side) and add the OWL index."""
        formatted = {key: value for key, value in line.items() if key != "move_out"}
        formatted["index"] = index
        formatted["move_out_id"] = line["move_out"].id
        return formatted

    def _format_html_sources_info(self, sources_to_lines):
        """Format used info from sources of sources_to_lines to be sent in an html request."""
        return {
            str(source): [
                self._format_html_source(s, s._name == "stock.picking") for s in source
            ]
            for source in sources_to_lines
        }

    def _format_html_source(self, source, is_picking=False):
        """Format used info from a single source to be sent in an html request."""
        formatted = {
            "id": source.id,
            "model": source._name,
            "name": source.display_name,
        }
        if is_picking:
            formatted.update(
                {
                    "priority": source.priority,
                    "partner_id": source.partner_id.id if source.partner_id else False,
                    "partner_name": (
                        source.partner_id.name if source.partner_id else False
                    ),
                },
            )
        return formatted
