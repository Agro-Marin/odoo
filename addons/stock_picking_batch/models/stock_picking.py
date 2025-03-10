# Part of Odoo. See LICENSE file for full copyright and licensing details.

from odoo import _, api, Command, fields, models
from odoo.osv import expression


class StockPicking(models.Model):
    _inherit = "stock.picking"


    batch_id = fields.Many2one(
        comodel_name="stock.picking.batch",
        string="Batch Transfer",
        check_company=True,
        copy=False,
        index=True,
        help="Batch associated to this transfer",
    )
    batch_sequence = fields.Integer(string="Sequence")


    # -------------------------------------------------------------------------
    # CRUD METHODS
    # -------------------------------------------------------------------------

    @api.model_create_multi
    def create(self, vals_list):
        pickings = super().create(vals_list)
        for picking, vals in zip(pickings, vals_list):
            if vals.get("batch_id"):
                if not picking.batch_id.picking_type_id:
                    picking.batch_id.picking_type_id = picking.picking_type_id[0]
                picking.batch_id._sanity_check()
        return pickings

    def write(self, vals):
        old_batches = self.batch_id
        res = super().write(vals)
        if vals.get("batch_id"):
            old_batches.filtered(lambda b: not b.picking_ids).state = "cancel"
            if not self.batch_id.picking_type_id:
                self.batch_id.picking_type_id = self.picking_type_id[0]
            self.batch_id._sanity_check()
            # assign batch users to batch pickings
            self.batch_id.picking_ids.assign_batch_user(self.batch_id.user_id.id)
        return res

    # -------------------------------------------------------------------------
    # ACTION METHODS
    # -------------------------------------------------------------------------

    def action_confirm(self):
        res = super().action_confirm()
        for picking in self:
            picking._find_auto_batch()
        return res

    def action_cancel(self):
        res = super().action_cancel()
        for picking in self:
            if picking.batch_id and any(
                picking.state != "cancel" for picking in picking.batch_id.picking_ids
            ):
                picking.batch_id = None
        return res

    def action_add_operations(self):
        view = self.env.ref("stock_picking_batch.view_move_line_tree_detailed_wave")
        return {
            "name": _("Add Operations"),
            "type": "ir.actions.act_window",
            "view_mode": "list",
            "view": view,
            "views": [(view.id, "list")],
            "res_model": "stock.move.line",
            "target": "new",
            "domain": [("picking_id", "in", self.ids), ("state", "!=", "done")],
            "context": dict(
                self.env.context,
                picking_to_wave=self.ids,
                active_wave_id=self.env.context.get("active_wave_id").id,
                search_default_by_location=True,
            ),
        }

    def action_view_batch(self):
        self.ensure_one()
        return {
            "type": "ir.actions.act_window",
            "res_model": "stock.picking.batch",
            "res_id": self.batch_id.id,
            "view_mode": "form",
        }

    def button_validate(self):
        res = super().button_validate()
        to_assign_ids = set()
        # Having non-done pickings after the `super()` call means it stopped early,
        # so we shouldn’t remove the pickings from batches yet.
        if not any(picking.state == "done" for picking in self):
            return res

        if self and self.env.context.get("pickings_to_detach"):
            pickings_to_detach = self.env["stock.picking"].browse(
                self.env.context["pickings_to_detach"]
            )
            pickings_to_detach.batch_id = False
            pickings_to_detach.move_ids.filtered(lambda m: not m.quantity).picked = (
                False
            )
            to_assign_ids.update(self.env.context["pickings_to_detach"])

        for picking in self:
            if picking.state != "done":
                continue

            # Avoid inconsistencies in states of the same batch when validating a single picking in a batch.
            if picking.batch_id and any(
                p.state != "done" for p in picking.batch_id.picking_ids
            ):
                picking.batch_id = None
            # If backorder were made, if auto-batch is enabled, seek a batch for each of them with the selected criterias.
            to_assign_ids.update(picking.backorder_ids.ids)

        # To avoid inconsistencies, all incorrect pickings must be removed before assigning backorder pickings
        assignable_pickings = self.env["stock.picking"].browse(to_assign_ids)
        for picking in assignable_pickings:
            picking._find_auto_batch()
        assignable_pickings.move_line_ids.with_context(
            skip_auto_waveable=True
        )._auto_wave()

        return res

    def _create_backorder(self, backorder_moves=None):
        pickings_to_detach = self.env["stock.picking"].browse(
            self.env.context.get("pickings_to_detach")
        )
        for picking in self:
            # Avoid inconsistencies in states of the same batch when validating a single picking in a batch.
            if (
                picking.batch_id
                and picking.state != "done"
                and any(
                    p not in self
                    for p in picking.batch_id.picking_ids - pickings_to_detach
                )
            ):
                picking.batch_id = None
        return super()._create_backorder(backorder_moves)

    def _find_auto_batch(self):
        self.ensure_one()
        # Check if auto_batch is enabled for this picking.
        if (
            not self.picking_type_id.auto_batch
            or not self.picking_type_id._is_auto_batch_grouped()
            or self.batch_id
            or not self.move_ids
            or not self._is_auto_batchable()
        ):
            return False

        # Try to find a compatible batch to insert the picking
        possible_batches = (
            self.env["stock.picking.batch"]
            .sudo()
            .search(self._get_possible_batches_domain())
        )
        for batch in possible_batches:
            if batch._is_picking_auto_mergeable(self):
                batch.picking_ids |= self
                return batch

        # If no batch were found, try to find a compatible picking and put them both in a new batch.
        possible_pickings = self.env["stock.picking"].search(
            self._get_possible_pickings_domain()
        )
        new_batch_data = {
            "picking_ids": [Command.link(self.id)],
            "company_id": self.company_id.id if self.company_id else False,
            "picking_type_id": self.picking_type_id.id,
            "description": self._get_auto_batch_description(),
        }
        for picking in possible_pickings:
            if self._is_auto_batchable(picking):
                # Add the picking to the new batch
                new_batch_data["picking_ids"].append(Command.link(picking.id))
                new_batch = (
                    self.env["stock.picking.batch"].sudo().create(new_batch_data)
                )
                if picking.picking_type_id.batch_auto_confirm:
                    new_batch.action_confirm()
                return new_batch

        # If nothing was found after those two steps, then create a batch with the current picking alone
        new_batch = self.env["stock.picking.batch"].sudo().create(new_batch_data)
        if self.picking_type_id.batch_auto_confirm:
            new_batch.action_confirm()
        return new_batch

    def assign_batch_user(self, user_id):
        pickings = self.filtered(lambda p: p.user_id.id != user_id)
        pickings.write({"user_id": user_id})
        for pick in pickings:
            if user_id:
                log_message = _(
                    "Assigned to %s Responsible", pick.batch_id._get_html_link()
                )
            else:
                log_message = _(
                    "Unassigned responsible from %s", pick.batch_id._get_html_link()
                )
            pick.message_post(body=log_message)

    def _get_possible_pickings_domain(self):
        self.ensure_one()
        domain = [
            ("id", "!=", self.id),
            ("company_id", "=", self.company_id.id if self.company_id else False),
            ("state", "=", "assigned"),
            ("picking_type_id", "=", self.picking_type_id.id),
            ("batch_id", "=", False),
        ]
        if self.picking_type_id.batch_group_by_partner:
            domain = expression.AND([domain, [("partner_id", "=", self.partner_id.id)]])
        if self.picking_type_id.batch_group_by_destination:
            domain = expression.AND(
                [
                    domain,
                    [("partner_id.country_id", "=", self.partner_id.country_id.id)],
                ]
            )
        if self.picking_type_id.batch_group_by_src_loc:
            domain = expression.AND(
                [domain, [("location_id", "=", self.location_id.id)]]
            )
        if self.picking_type_id.batch_group_by_dest_loc:
            domain = expression.AND(
                [domain, [("location_dest_id", "=", self.location_dest_id.id)]]
            )

        return domain

    def _get_possible_batches_domain(self):
        self.ensure_one()
        domain = [
            (
                "state",
                "in",
                (
                    ("draft", "in_progress")
                    if self.picking_type_id.batch_auto_confirm
                    else ("draft",)
                ),
            ),
            ("picking_type_id", "=", self.picking_type_id.id),
            ("company_id", "=", self.company_id.id if self.company_id else False),
            ("is_wave", "=", False),
        ]
        if self.picking_type_id.batch_group_by_partner:
            domain = expression.AND(
                [domain, [("picking_ids.partner_id", "=", self.partner_id.id)]]
            )
        if self.picking_type_id.batch_group_by_destination:
            domain = expression.AND(
                [
                    domain,
                    [
                        (
                            "picking_ids.partner_id.country_id",
                            "=",
                            self.partner_id.country_id.id,
                        )
                    ],
                ]
            )
        if self.picking_type_id.batch_group_by_src_loc:
            domain = expression.AND(
                [domain, [("picking_ids.location_id", "=", self.location_id.id)]]
            )
        if self.picking_type_id.batch_group_by_dest_loc:
            domain = expression.AND(
                [
                    domain,
                    [("picking_ids.location_dest_id", "=", self.location_dest_id.id)],
                ]
            )

        return domain

    def _get_auto_batch_description(self):
        """Get the description of the automatically created batch based on the grouped pickings and grouping criteria"""
        self.ensure_one()
        description_items = []
        if self.picking_type_id.batch_group_by_partner and self.partner_id:
            description_items.append(self.partner_id.name or "")
        if (
            self.picking_type_id.batch_group_by_destination
            and self.partner_id.country_id
        ):
            description_items.append(self.partner_id.country_id.name)
        if self.picking_type_id.batch_group_by_src_loc and self.location_id:
            description_items.append(self.location_id.display_name)
        if self.picking_type_id.batch_group_by_dest_loc and self.location_dest_id:
            description_items.append(self.location_dest_id.display_name)
        return ", ".join(description_items)

    def _should_show_transfers(self):
        if len(self.batch_id) == 1 and len(self) == (
            len(self.batch_id.picking_ids)
            - len(self.env.context.get("pickings_to_detach", []))
        ):
            return False

        return super()._should_show_transfers()

    def _is_auto_batchable(self, picking=None):
        """Verifies if a picking can be put in a batch with another picking without violating auto_batch constrains."""
        if self.state != "assigned":
            return False

        res = True
        if not picking:
            picking = self.env["stock.picking"]
        if self.picking_type_id.batch_max_lines:
            res = res and (
                len(self.move_ids) + len(picking.move_ids)
                <= self.picking_type_id.batch_max_lines
            )
        if self.picking_type_id.batch_max_pickings:
            # Sounds absurd. BUT if we put "batch max picking" to a value <= 1, makes sense ... Or not. Because then there is no point to batch.
            res = res and self.picking_type_id.batch_max_pickings > 1
        return res
