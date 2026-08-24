from odoo import api, fields, models
from odoo.exceptions import UserError
from odoo.fields import Command


class MrpProductionSerials(models.TransientModel):
    _name = "mrp.production.serials"
    _description = "Assign serial numbers to production order"

    production_id = fields.Many2one("mrp.production", "Production")

    workorder_id = fields.Many2one("mrp.workorder", "Workorder")

    lot_name = fields.Char(
        "First SN", compute="_compute_lot_name", store=True, readonly=False
    )
    lot_quantity = fields.Integer(
        "Number of SN", compute="_compute_lot_quantity", store=True, readonly=False
    )

    serial_numbers = fields.Text(
        "Produced Serial Numbers",
        compute="_compute_lot_name",
        store=True,
        readonly=False,
    )

    @api.depends("production_id")
    def _compute_lot_name(self):
        for wizard in self:
            wizard.serial_numbers = "\n".join(
                wizard.production_id.lot_producing_ids.mapped("name")
            )
            if wizard.lot_name:
                continue
            wizard.lot_name = wizard.production_id.lot_producing_ids[:1].name
            if not wizard.lot_name:
                wizard.lot_name = wizard.production_id.product_id.next_serial

    @api.depends("production_id")
    def _compute_lot_quantity(self):
        for wizard in self:
            wizard.lot_quantity = wizard.production_id.product_qty

    def _serial_names(self):
        """The serial numbers typed into the wizard: blanks dropped, repeats folded.

        One definition, because the two callers disagreed. The onchange folded
        repeats and `_parse_serial_numbers` did not, so the form and every other
        caller saw different lists -- and `action_split_and_assign_serials` splits
        into `len(names)` orders and then `zip(..., strict=True)`s them against the
        lots the parse returned. A serial typed twice made those two lengths differ
        and the wizard died with `ValueError: zip() argument 2 is shorter than
        argument 1`, a traceback rather than a message.
        """
        self.ensure_one()
        return list(
            dict.fromkeys(
                name for name in (self.serial_numbers or "").split("\n") if name.strip()
            )
        )

    @api.onchange("serial_numbers")
    def _onchange_serial_numbers(self):
        self.serial_numbers = "\n".join(self._serial_names())

    def action_generate_serial_numbers(self):
        self.ensure_one()
        if self.lot_name and self.lot_quantity:
            lots = self.env["stock.lot"].generate_lot_names(
                self.lot_name, self.lot_quantity
            )
            self.serial_numbers = "\n".join(lots)
            self._onchange_serial_numbers()
        action = self.env["ir.actions.actions"]._get_action_dict_by_xml_id(
            "mrp.action_assign_serial_numbers"
        )
        action["res_id"] = self.id
        return action

    def action_split_and_assign_serials(self):
        self.ensure_one()
        lots = self._parse_serial_numbers()

        split_amounts = {self.production_id: [1] * len(lots)}
        mos = self.production_id._split_productions(amounts=split_amounts)
        # `_get_split_amounts` appends the leftover as one *more* order when the
        # serials do not cover the whole quantity, so `mos` can be longer than
        # `lots` -- and it was zipped strictly against them, so supplying one serial
        # for an order of five died with `ValueError: zip() argument 2 is shorter
        # than argument 1` instead of splitting off the one unit that has a serial.
        # The orders come back in the order the amounts were asked for, so the
        # leftover is last and is the one that keeps no serial.
        for mo, serial in zip(mos[: len(lots)], lots, strict=True):
            mo.lot_producing_ids = [Command.link(serial.id)]
        return self._closing_action(mos)

    def action_apply(self):
        self.ensure_one()
        lots = self._parse_serial_numbers()
        self.production_id.lot_producing_ids = lots
        if self.production_id.qty_producing != len(
            self.production_id.lot_producing_ids
        ):
            self.production_id.qty_producing = len(self.production_id.lot_producing_ids)
        (self.workorder_id or self.production_id).set_qty_producing()
        return self._closing_action()

    def _closing_action(self, mos=False):
        mos = mos or self.production_id
        print_actions = mos._autoprint_mass_generated_lots()
        if print_actions:
            return {
                "type": "ir.actions.client",
                "tag": "do_multi_print",
                "context": {},
                "params": {
                    "reports": print_actions,
                },
            }
        return {"type": "ir.actions.act_window_close"}

    def _parse_serial_numbers(self):
        self.ensure_one()
        if not self.serial_numbers:
            raise UserError(self.env._("There is no serial numbers to apply."))
        lots = self._serial_names()
        if not lots:
            raise UserError(self.env._("No valid serial numbers provided."))
        existing_lots = self.env["stock.lot"].search(
            [
                "|",
                ("company_id", "=", False),
                ("company_id", "=", self.production_id.company_id.id),
                ("product_id", "=", self.production_id.product_id.id),
                ("name", "in", lots),
            ]
        )
        existing_lot_names = existing_lots.mapped("name")
        new_lots_vals = []
        sequence = self.production_id.product_id.lot_sequence_id
        for lot_name in sorted(lots):
            if lot_name in existing_lot_names:
                continue
            if sequence and lot_name == sequence.get_next_char(
                sequence.number_next_actual
            ):
                sequence.sudo().number_next_actual += 1
            new_lots_vals.append(
                {
                    "name": lot_name,
                    "product_id": self.production_id.product_id.id,
                }
            )
        new_lots = self.env["stock.lot"].create(new_lots_vals)
        return existing_lots + new_lots
