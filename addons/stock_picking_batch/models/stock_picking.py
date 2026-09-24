from odoo import api, models
from odoo.fields import Command, Domain
from odoo.libs.debug_log import DebugLog

_debug = DebugLog(__name__)


class StockPicking(models.Model):
    _inherit = "stock.picking"

    @api.model_create_multi
    def create(self, vals_list):
        pickings = super().create(vals_list)
        pickings.batch_id._update_picking_type_from_pickings()
        pickings.batch_id._check_pickings_are_allowed()
        return pickings

    def write(self, vals):
        res = super().write(vals)
        if "batch_id" in vals:
            _debug.lifecycle(
                "picking_batch_write", pickings=self, batch=vals["batch_id"]
            )
        if vals.get("batch_id"):
            self.batch_id._update_picking_type_from_pickings()
            self.batch_id._check_pickings_are_allowed()
            if self.batch_id.user_id:
                self.update_batch_user(self.batch_id.user_id.id)
        return res

    def action_confirm(self):
        res = super().action_confirm()
        for picking in self:
            picking._resolve_auto_batch()
        return res

    def _rebatch_after_validation(self):
        super()._rebatch_after_validation()
        _debug.pipeline("batch_validate_rebatch", pickings=self)
        for picking in self:
            picking._resolve_auto_batch()
        if lines := self.move_line_ids:
            lines.with_context(skip_auto_waveable=True)._auto_wave()

    @_debug.perf.timed
    def _resolve_auto_batch(self):
        self.check_singleton()
        if not self.picking_type_id._is_auto_batch_grouped():
            skip = "type_not_grouped"
        elif self.batch_id:
            skip = "already_batched"
        elif not self.move_ids:
            skip = "no_moves"
        elif not self._is_auto_batchable():
            skip = "not_batchable"
        else:
            skip = None
        if skip:
            _debug.logic("auto_batch_skip", picking=self, reason=skip)
            return False

        possible_batches = (
            self.env["stock.picking.batch"]
            .sudo()
            .search(self._get_domain_possible_batches())
        )
        _debug.logic("auto_batch_candidates", picking=self, batches=possible_batches)
        for batch in possible_batches:
            if batch._is_auto_mergeable(**self._get_auto_merge_amounts()):
                _debug.pipeline("auto_batch_join", picking=self, batch=batch)
                batch.picking_ids |= self
                return batch

        possible_pickings = self.env["stock.picking"].search(
            self._get_domain_possible_pickings()
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
        _debug.pipeline(
            "auto_batch_create",
            picking=self,
            batch=new_batch,
            partner_pickings=len(new_batch_data["picking_ids"]) - 1,
            candidates=len(possible_pickings),
            auto_confirm=self.picking_type_id.batch_auto_confirm,
        )
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
        _debug.logic(
            "auto_batchable",
            picking=self,
            partner=picking,
            max_lines=self.picking_type_id.batch_max_lines,
            max_pickings=self.picking_type_id.batch_max_pickings,
            result=res,
        )
        return res

    def _get_domain_possible_pickings(self):
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

    def _get_domain_possible_batches(self):
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
            if value and (label := value[criterion.label_field]):
                description_items.append(label)
        return ", ".join(description_items)

    def _add_to_wave_post_picking_split_hook(self):
        pass

    def action_view_batch(self):
        self.check_singleton()
        return {
            "type": "ir.actions.act_window",
            "res_model": "stock.picking.batch",
            "res_id": self.batch_id.id,
            "view_mode": "form",
        }

    @api.depends("partner_id")
    @api.depends_context("display_name_partner")
    def _compute_display_name(self):
        super()._compute_display_name()
        if not self.env.context.get("display_name_partner"):
            return
        for picking in self.filtered("partner_id"):
            picking.display_name = (
                f"{picking.display_name} - {picking.partner_id.display_name}"
            )
        return
