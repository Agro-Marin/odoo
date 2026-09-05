from typing import NamedTuple

from odoo import _, api, fields, models
from odoo.exceptions import ValidationError
from odoo.fields import Command, Domain


class GroupingCriterion(NamedTuple):
    line_path: str
    label_field: str
    picking_path: str = ""
    wave_field: str = ""

    @property
    def batch_path(self):
        if self.picking_path:
            return f"picking_ids.{self.picking_path}"
        return f"move_line_ids.{self.line_path}"


class StockPickingType(models.Model):
    _inherit = "stock.picking.type"

    count_picking_batch = fields.Integer(compute="_compute_picking_count")
    count_picking_wave = fields.Integer(compute="_compute_picking_count")
    auto_batch = fields.Boolean(
        "Automatic Batches",
        help="Automatically put pickings into batches as they are confirmed when possible.",
    )
    batch_group_by_partner = fields.Boolean(
        "Contact", help="Automatically group batches by contacts."
    )
    batch_group_by_destination = fields.Boolean(
        "Destination Country",
        help="Automatically group batches by destination country.",
    )
    batch_group_by_src_loc = fields.Boolean(
        "Group by Source Location",
        help="Automatically group batches by their source location.",
    )
    batch_group_by_dest_loc = fields.Boolean(
        "Group by Destination Location",
        help="Automatically group batches by their destination location.",
    )
    wave_group_by_product = fields.Boolean(
        "Product",
        help="Split transfers by product then group transfers that have the same product.",
    )
    wave_group_by_category = fields.Boolean(
        "Product Category",
        help="Split transfers by product category, then group transfers that have the same product category.",
    )
    wave_category_ids = fields.Many2many(
        "product.category",
        string="Wave Product Categories",
        help="Categories to consider when grouping waves.",
    )
    wave_group_by_location = fields.Boolean(
        "Location",
        help="Split transfers by defined locations, then group transfers with the same location.",
    )
    wave_location_ids = fields.Many2many(
        "stock.location",
        string="Wave Locations",
        help="Locations to consider when grouping waves.",
        domain="[('usage', '=', 'internal')]",
    )
    batch_max_lines = fields.Integer(
        "Maximum lines",
        help="A transfer will not be automatically added to batches that will exceed this number of lines if the transfer is added to it.\n"
        "Leave this value as '0' if no line limit.",
    )
    batch_max_pickings = fields.Integer(
        "Maximum transfers",
        help="A transfer will not be automatically added to batches that will exceed this number of transfers.\n"
        "Leave this value as '0' if no transfer limit.",
    )
    batch_auto_confirm = fields.Boolean("Auto-confirm", default=True)
    batch_properties_definition = fields.PropertiesDefinition("Batch Properties")

    def _compute_picking_count(self):
        super()._compute_picking_count()
        data = self.env["stock.picking.batch"]._read_group(
            [
                ("state", "not in", ("done", "cancel")),
                ("picking_type_id", "in", self.ids),
            ],
            ["picking_type_id", "is_wave"],
            ["__count"],
        )
        count = {
            (picking_type.id, is_wave): count for picking_type, is_wave, count in data
        }
        for record in self:
            record.count_picking_wave = count.get((record.id, True), 0)
            record.count_picking_batch = count.get((record.id, False), 0)

    def action_batch(self):
        action = self._prepare_action_by_xml_id(
            "stock_picking_batch.stock_picking_batch_action"
        )
        if self.env.context.get("view_mode"):
            del action["mobile_view_mode"]
            del action["views"]
            action["view_mode"] = self.env.context["view_mode"]
        return action

    def action_wave(self):
        return self._prepare_action_by_xml_id(
            "stock_picking_batch.action_picking_tree_wave"
        )

    def _is_auto_batch_grouped(self):
        self.check_singleton()
        return self.auto_batch and any(
            self[key] for key in self._get_batch_group_by_keys()
        )

    def _is_auto_wave_grouped(self):
        self.check_singleton()
        return self.auto_batch and any(
            self[key] for key in self._get_wave_group_by_keys()
        )

    @api.model
    def _get_batch_grouping_criteria(self):
        return {
            "batch_group_by_partner": GroupingCriterion(
                "move_id.partner_id", "name", "partner_id", "wave_partner_id"
            ),
            "batch_group_by_destination": GroupingCriterion(
                "move_id.partner_id.country_id",
                "name",
                "partner_id.country_id",
                "wave_country_id",
            ),
            "batch_group_by_src_loc": GroupingCriterion(
                "location_id", "display_name", "location_id", "wave_source_location_id"
            ),
            "batch_group_by_dest_loc": GroupingCriterion(
                "location_dest_id",
                "display_name",
                "location_dest_id",
                "wave_dest_location_id",
            ),
        }

    @api.model
    def _get_wave_grouping_criteria(self):
        return {
            "wave_group_by_product": GroupingCriterion(
                "product_id", "display_name", wave_field="wave_product_id"
            ),
            "wave_group_by_category": GroupingCriterion(
                "product_id.categ_id", "complete_name", wave_field="wave_category_id"
            ),
        }

    @api.model
    def _get_grouping_criteria(self):
        return {
            **self._get_batch_grouping_criteria(),
            **self._get_wave_grouping_criteria(),
        }

    def _get_active_grouping_criteria(self, criteria):
        self.check_singleton()
        return {key: criterion for key, criterion in criteria.items() if self[key]}

    def _get_active_batch_criteria(self):
        return self._get_active_grouping_criteria(self._get_batch_grouping_criteria())

    def _get_active_wave_criteria(self):
        return self._get_active_grouping_criteria(self._get_grouping_criteria())

    def _get_nearest_wave_location(self, location):
        self.check_singleton()
        wave_location_ids = set(self.wave_location_ids.ids)
        while location and location.id not in wave_location_ids:
            location = location.location_id
        return location

    @api.model
    def _get_batch_group_by_keys(self):
        return list(self._get_batch_grouping_criteria())

    @api.model
    def _get_wave_group_by_keys(self):
        return [*self._get_wave_grouping_criteria(), "wave_group_by_location"]

    @api.model
    def _get_batch_and_wave_group_by_keys(self):
        return self._get_batch_group_by_keys() + self._get_wave_group_by_keys()

    @api.constrains(
        lambda self: self._get_batch_and_wave_group_by_keys() + ["auto_batch"]
    )
    def _check_auto_batch_group_by(self):
        group_by_keys = self._get_batch_and_wave_group_by_keys()
        for picking_type in self:
            if not picking_type.auto_batch:
                continue
            if not any(picking_type[key] for key in group_by_keys):
                raise ValidationError(
                    _(
                        "If the Automatic Batches feature is enabled, at least one 'Group by' option must be selected."
                    )
                )

    @api.constrains("batch_max_lines", "batch_max_pickings")
    def _check_batch_limits(self):
        for picking_type in self:
            if picking_type.batch_max_lines < 0 or picking_type.batch_max_pickings < 0:
                raise ValidationError(
                    _(
                        "Batch limits cannot be negative. Leave a limit at '0' to disable it."
                    )
                )


class StockPicking(models.Model):
    _inherit = "stock.picking"

    batch_id = fields.Many2one(
        "stock.picking.batch",
        string="Batch Transfer",
        check_company=True,
        help="Batch associated to this transfer",
        index=True,
        copy=False,
    )
    batch_sequence = fields.Integer(string="Sequence")

    @api.model_create_multi
    def create(self, vals_list):
        pickings = super().create(vals_list)
        pickings.batch_id._set_picking_type_from_pickings()
        pickings.batch_id._check_pickings_are_allowed()
        return pickings

    def write(self, vals):
        res = super().write(vals)
        if vals.get("batch_id"):
            self.batch_id._set_picking_type_from_pickings()
            self.batch_id._check_pickings_are_allowed()
            self.batch_id.picking_ids.update_batch_user(self.batch_id.user_id.id)
        return res

    def action_confirm(self):
        res = super().action_confirm()
        for picking in self:
            picking._find_auto_batch()
        return res

    def button_validate(self):
        res = super().button_validate()
        to_assign_ids = set()
        if not any(picking.state == "done" for picking in self):
            return res
        if self and self.env.context.get("pickings_to_detach"):
            pickings_to_detach = self.env["stock.picking"].browse(
                self.env.context["pickings_to_detach"]
            )
            pickings_to_detach.batch_id = False
            pickings_to_detach.move_ids.filtered(
                lambda m: not m.quantity
            ).picked = False
            to_assign_ids.update(self.env.context["pickings_to_detach"])

        for picking in self:
            if picking.state != "done":
                continue
            if picking.batch_id and any(
                p.state != "done" for p in picking.batch_id.picking_ids
            ):
                picking.batch_id = None
            to_assign_ids.update(picking.backorder_ids.ids)

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

    def _should_show_transfers(self):
        detached = self.browse(self.env.context.get("pickings_to_detach"))
        if len(self.batch_id) == 1 and self == self.batch_id.picking_ids - detached:
            return False
        return super()._should_show_transfers()

    def _find_auto_batch(self):
        self.check_singleton()
        if (
            not self.picking_type_id._is_auto_batch_grouped()
            or self.batch_id
            or not self.move_ids
            or not self._is_auto_batchable()
        ):
            return False

        possible_batches = (
            self.env["stock.picking.batch"]
            .sudo()
            .search(self._get_possible_batches_domain())
        )
        for batch in possible_batches:
            if batch._is_auto_mergeable(**self._get_auto_merge_amounts()):
                batch.picking_ids |= self
                return batch

        possible_pickings = self.env["stock.picking"].search(
            self._get_possible_pickings_domain()
        )
        new_batch_data = {
            "picking_ids": [Command.link(self.id)],
            "company_id": self.company_id.id,
            "picking_type_id": self.picking_type_id.id,
            "description": self._get_auto_batch_description(),
            "user_id": self.user_id.id,
        }
        for picking in possible_pickings:
            if self._is_auto_batchable(picking):
                new_batch_data["picking_ids"].append(Command.link(picking.id))
                break
        new_batch = self.env["stock.picking.batch"].sudo().create(new_batch_data)
        if self.picking_type_id.batch_auto_confirm:
            new_batch.action_confirm()
        return new_batch

    def _get_auto_merge_amounts(self):
        self.check_singleton()
        return {"moves": len(self.move_ids), "pickings": 1}

    def _is_auto_batchable(self, picking=None):
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
            res = res and self.picking_type_id.batch_max_pickings > 1
        return res

    def _get_possible_pickings_domain(self):
        self.check_singleton()
        domain = [
            ("id", "!=", self.id),
            ("company_id", "=", self.company_id.id),
            ("state", "=", "assigned"),
            ("picking_type_id", "=", self.picking_type_id.id),
            ("batch_id", "=", False),
        ]
        domain.extend(
            (criterion.picking_path, "=", self.mapped(criterion.picking_path).id)
            for criterion in self.picking_type_id._get_active_batch_criteria().values()
        )

        return Domain(domain)

    def _get_possible_batches_domain(self):
        self.check_singleton()
        domain = [
            (
                "state",
                "in",
                ("draft", "in_progress")
                if self.picking_type_id.batch_auto_confirm
                else ("draft",),
            ),
            ("picking_type_id", "=", self.picking_type_id.id),
            ("company_id", "=", self.company_id.id),
            ("is_wave", "=", False),
        ]
        domain.extend(
            (criterion.batch_path, "=", self.mapped(criterion.picking_path).id)
            for criterion in self.picking_type_id._get_active_batch_criteria().values()
        )
        if self.env.context.get("batches_to_validate"):
            domain.append(("id", "not in", self.env.context.get("batches_to_validate")))

        return Domain(domain)

    def _get_auto_batch_description(self):
        self.check_singleton()
        description_items = []
        for criterion in self.picking_type_id._get_active_batch_criteria().values():
            value = self.mapped(criterion.picking_path)
            if value:
                description_items.append(value[criterion.label_field])
        return ", ".join(description_items)

    def _is_single_transfer(self):
        return super()._is_single_transfer() or len(self.batch_id) == 1

    def _add_to_wave_post_picking_split_hook(self):
        pass

    def update_batch_user(self, user_id):
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

    def action_view_batch(self):
        self.check_singleton()
        return {
            "type": "ir.actions.act_window",
            "res_model": "stock.picking.batch",
            "res_id": self.batch_id.id,
            "view_mode": "form",
        }
