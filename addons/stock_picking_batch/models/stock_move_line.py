from collections import defaultdict

from odoo import _, fields, models
from odoo.fields import Command, Domain
from odoo.tools.misc import OrderedSet


class StockMoveLine(models.Model):
    _inherit = "stock.move.line"

    batch_id = fields.Many2one(related="picking_id.batch_id")

    def action_view_add_to_wave(self):
        if "active_wave_id" in self.env.context:
            wave = self.env["stock.picking.batch"].browse(
                self.env.context.get("active_wave_id")
            )
            return self._add_to_wave(wave)
        view = self.env.ref("stock_picking_batch.stock_add_to_wave_form")
        return {
            "name": _("Add to Wave"),
            "type": "ir.actions.act_window",
            "view_mode": "form",
            "res_model": "stock.add.to.wave",
            "views": [(view.id, "form")],
            "view_id": view.id,
            "target": "new",
        }

    def _prepare_wave_picking_vals(self, wave, picking, lines):
        line_by_move = defaultdict(lambda: self.env["stock.move.line"])
        qty_by_move = defaultdict(float)
        for line in lines:
            move = line.move_id
            line_by_move[move] |= line
            qty = line.product_uom_id._compute_quantity(
                line.quantity, line.product_id.uom_id, rounding_method="HALF-UP"
            )
            qty_by_move[line.move_id] += qty

        if lines == picking.move_line_ids and lines.move_id == picking.move_ids:
            add_all_moves = True
            for move, qty in qty_by_move.items():
                if move.product_uom_id.is_zero(qty):
                    add_all_moves = False
                    break
            if add_all_moves:
                wave.picking_ids = [Command.link(picking.id)]
                return None

        picking_to_wave_vals = picking.copy_data(
            {
                "move_ids": [],
                "move_line_ids": [],
                "batch_id": wave.id,
                "date_planned": picking.date_planned,
            }
        )[0]
        for move, move_lines in line_by_move.items():
            if move_lines == move.move_line_ids:
                picking_to_wave_vals["move_ids"] += [Command.link(move.id)]
            else:
                new_move = move._split(qty_by_move[move])
                if not new_move:
                    continue
                new_move[0]["move_line_ids"] = [Command.set(move_lines.ids)]
                picking_to_wave_vals["move_ids"] += [Command.create(new_move[0])]
            picking_to_wave_vals["move_line_ids"] += [
                Command.link(line.id) for line in move_lines
            ]

        if not picking_to_wave_vals["move_ids"]:
            return None
        return picking_to_wave_vals

    def _get_add_to_wave_action(self, wave, notification_title):
        if self.env.context.get("from_wave_form"):
            return {
                "type": "ir.actions.client",
                "tag": "soft_reload",
            }
        return {
            "type": "ir.actions.client",
            "tag": "display_notification",
            "params": {
                "title": notification_title,
                "message": "%s",
                "links": [
                    {
                        "label": wave.name,
                        "url": f"/odoo/action-stock_picking_batch.action_picking_tree_wave/{wave.id}",
                    }
                ],
                "sticky": False,
                "next": {"type": "ir.actions.act_window_close"},
            },
        }

    def _add_to_wave(self, wave=False, description=False):

        if not wave:
            wave = self.env["stock.picking.batch"].create(
                {
                    "is_wave": True,
                    "picking_type_id": self.picking_type_id[:1].id,
                    "user_id": self.env.context.get("active_owner_id"),
                    "description": description,
                }
            )
            notification_title = _("The following wave transfer has been created")
        else:
            notification_title = _("The following wave transfer has been updated")
        line_by_picking = defaultdict(lambda: self.env["stock.move.line"])
        for line in self:
            line_by_picking[line.picking_id] |= line
        picking_to_wave_vals_list = []
        split_pickings_ids = set()
        for picking, lines in line_by_picking.items():
            picking_to_wave_vals = self._prepare_wave_picking_vals(wave, picking, lines)
            if picking_to_wave_vals is None:
                continue
            split_pickings_ids.add(picking.id)
            picking_to_wave_vals_list.append(picking_to_wave_vals)

        if picking_to_wave_vals_list:
            split_pickings = self.env["stock.picking"].browse(
                split_pickings_ids
            ) | self.env["stock.picking"].create(picking_to_wave_vals_list)
            split_pickings._add_to_wave_post_picking_split_hook()
        if wave.picking_ids and wave.picking_type_id.batch_auto_confirm:
            wave.action_confirm()
        return self._get_add_to_wave_action(wave, notification_title)

    def _is_auto_waveable(self):
        self.check_singleton()
        if (  # noqa: SIM103
            not self.picking_id
            or (
                (
                    self.picking_id.state != "assigned"
                    or self.product_uom_id.is_zero(self.quantity)
                )
                and not self.env.context.get("skip_auto_waveable")
            )
            or self.batch_id.is_wave
            or not self.picking_type_id._is_auto_wave_grouped()
            or (
                self.picking_type_id.wave_group_by_category
                and self.product_id.categ_id
                not in self.picking_type_id.wave_category_ids
            )
        ):
            return False
        return True

    def _auto_wave(self):
        wave_locs_by_picking_type = {}
        for picking_type in self.picking_type_id:
            if not picking_type.wave_group_by_location:
                continue
            wave_locs_by_picking_type[picking_type] = set(
                picking_type.wave_location_ids.ids
            )
        lines_nearest_parent_locations = defaultdict(lambda: self.env["stock.location"])
        batchable_line_ids = OrderedSet()
        for line in self:
            if not line._is_auto_waveable():
                continue
            if not line.picking_type_id.wave_group_by_location:
                batchable_line_ids.add(line.id)
                continue
            wave_locs_set = wave_locs_by_picking_type[line.picking_type_id]
            loc = line.location_id
            while loc:
                if loc.id in wave_locs_set:
                    lines_nearest_parent_locations[line] = loc
                    batchable_line_ids.add(line.id)
                    break
                loc = loc.location_id
        batchable_lines = self.env["stock.move.line"].browse(batchable_line_ids)

        remaining_line_ids = batchable_lines._auto_wave_lines_into_existing_waves(
            nearest_parent_locations=lines_nearest_parent_locations
        )
        remaining_lines = self.env["stock.move.line"].browse(remaining_line_ids)
        if remaining_lines:
            remaining_lines._auto_wave_lines_into_new_waves(
                nearest_parent_locations=lines_nearest_parent_locations
            )

    def _get_potential_existing_waves_extra_domain(self, domain_list, picking_type):
        return domain_list

    def _get_potential_new_waves_extra_domain(self, domain_list, picking_type):
        return domain_list

    def _is_potential_existing_wave_extra(self, wave):
        return True

    def _is_new_potential_line_extra(self, potential_line):
        return True

    def _get_potential_existing_waves(self, picking_type, batches_to_validate_ids):
        domains = [
            Domain("picking_type_id", "=", picking_type.id),
            Domain("company_id", "in", self.company_id.ids),
            Domain("is_wave", "=", True),
        ]
        if picking_type.batch_auto_confirm:
            domains.append(Domain("state", "not in", ["done", "cancel"]))
        else:
            domains.append(Domain("state", "=", "draft"))
        domains.extend(
            Domain(criterion.batch_path, "in", self.mapped(criterion.line_path).ids)
            for criterion in self._get_active_wave_criteria(picking_type).values()
        )
        if batches_to_validate_ids:
            domains.append(Domain("id", "not in", batches_to_validate_ids))
        domains = self._get_potential_existing_waves_extra_domain(domains, picking_type)

        return self.env["stock.picking.batch"].search(Domain.AND(domains))

    def _get_waves_nearest_parent_locations(self, picking_type, potential_waves):
        waves_nearest_parent_locations = defaultdict(int)
        if not picking_type.wave_group_by_location:
            return waves_nearest_parent_locations, potential_waves

        valid_wave_ids = set()
        for wave in potential_waves:
            for wave_location in reversed(picking_type.wave_location_ids):
                if all(
                    loc._is_child_of(wave_location)
                    for loc in wave.move_line_ids.location_id
                ):
                    waves_nearest_parent_locations[wave] = wave_location.id
                    valid_wave_ids.add(wave.id)
                    break
        return (
            waves_nearest_parent_locations,
            self.env["stock.picking.batch"].browse(valid_wave_ids),
        )

    def _get_active_wave_criteria(self, picking_type):
        return picking_type._get_active_grouping_criteria(
            picking_type._get_grouping_criteria()
        )

    def _is_wave_grouping_compatible(
        self,
        wave,
        picking_type,
        waves_nearest_parent_locations,
        nearest_parent_locations,
    ):
        self.check_singleton()
        if self.company_id != wave.company_id:
            return False
        for criterion in self._get_active_wave_criteria(picking_type).values():
            if self.mapped(criterion.line_path) != wave.mapped(criterion.batch_path):
                return False
        if (
            picking_type.wave_group_by_location
            and waves_nearest_parent_locations[wave]
            != nearest_parent_locations[self].id
        ):
            return False
        return self._is_potential_existing_wave_extra(wave)

    def _get_matching_existing_wave(
        self,
        potential_waves,
        picking_type,
        tallies,
        waves_nearest_parent_locations,
        nearest_parent_locations,
    ):
        self.check_singleton()
        for wave in potential_waves:
            if not self._is_wave_grouping_compatible(
                wave,
                picking_type,
                waves_nearest_parent_locations,
                nearest_parent_locations,
            ):
                continue

            wave_new_move_ids = tallies["moves"][wave]
            wave_new_picking_ids = tallies["pickings"][wave]
            wave_move_ids = set(wave.move_line_ids.mapped("move_id.id"))
            wave_picking_ids = set(wave.move_line_ids.mapped("picking_id.id"))
            adds_a_move = (
                self.move_id.id not in wave_move_ids
                and self.move_id.id not in wave_new_move_ids
            )
            adds_a_picking = (
                self.picking_id.id not in wave_picking_ids
                and self.picking_id.id not in wave_new_picking_ids
            )
            if not wave._is_auto_mergeable(
                moves=len(wave_new_move_ids) + 1 if adds_a_move else 0,
                pickings=len(wave_new_picking_ids) + 1 if adds_a_picking else 0,
                weight=tallies["weight"][wave]
                + self.product_id.weight * self.quantity_product_uom,
            ):
                continue

            if self.move_id.id not in wave_move_ids:
                tallies["moves"][wave].add(self.move_id.id)
            if self.picking_id.id not in wave_picking_ids:
                tallies["pickings"][wave].add(self.picking_id.id)
            tallies["weight"][wave] += (
                self.product_id.weight * self.quantity_product_uom
            )
            return wave
        return False

    def _auto_wave_lines_into_existing_waves(self, nearest_parent_locations=False):
        remaining_lines = OrderedSet()
        batches_to_validate_ids = self.env.context.get("batches_to_validate", False)
        for picking_type, lines in self.grouped(lambda l: l.picking_type_id).items():
            if not lines:
                continue
            potential_waves = lines._get_potential_existing_waves(
                picking_type, batches_to_validate_ids
            )
            wave_to_new_lines = defaultdict(set)

            tallies = {
                "moves": defaultdict(set),
                "pickings": defaultdict(set),
                "weight": defaultdict(float),
            }

            waves_nearest_parent_locations, potential_waves = (
                lines._get_waves_nearest_parent_locations(picking_type, potential_waves)
            )

            for line in lines:
                wave = line._get_matching_existing_wave(
                    potential_waves,
                    picking_type,
                    tallies,
                    waves_nearest_parent_locations,
                    nearest_parent_locations,
                )
                if wave:
                    wave_to_new_lines[wave].add(line.id)
                else:
                    remaining_lines.add(line.id)
            for wave, line_ids in wave_to_new_lines.items():
                self.env["stock.move.line"].browse(line_ids)._add_to_wave(wave)
        return list(remaining_lines)

    def _get_potential_new_wave_lines(self, picking_type, lines):
        domains = [
            Domain(
                [
                    ("id", "in", lines.ids),
                    ("company_id", "in", self.company_id.ids),
                    ("picking_id.state", "=", "assigned"),
                    ("picking_type_id", "=", picking_type.id),
                    "|",
                    ("batch_id", "=", False),
                    ("batch_id.is_wave", "=", False),
                ]
            )
        ]
        domains.extend(
            Domain(criterion.line_path, "in", lines.mapped(criterion.line_path).ids)
            for criterion in lines._get_active_wave_criteria(picking_type).values()
        )
        if picking_type.wave_group_by_location:
            domains.append(
                Domain("location_id", "child_of", picking_type.wave_location_ids.ids)
            )
        domains = lines._get_potential_new_waves_extra_domain(domains, picking_type)

        potential_lines = self.env["stock.move.line"].search(Domain.AND(domains))
        lines_nearest_parent_locations = defaultdict(int)
        if picking_type.wave_group_by_location:
            for line in potential_lines:
                for location in reversed(picking_type.wave_location_ids):
                    if line.location_id._is_child_of(location):
                        lines_nearest_parent_locations[line] = location.id
                        break
        return potential_lines, lines_nearest_parent_locations

    def _is_new_wave_grouping_compatible(
        self,
        potential_line,
        picking_type,
        lines_nearest_parent_locations,
        nearest_parent_locations,
    ):
        self.check_singleton()
        if self.id == potential_line.id or self.company_id != potential_line.company_id:
            return False
        for criterion in self._get_active_wave_criteria(picking_type).values():
            if self.mapped(criterion.line_path) != potential_line.mapped(
                criterion.line_path
            ):
                return False
        if (
            picking_type.wave_group_by_location
            and lines_nearest_parent_locations[potential_line]
            != nearest_parent_locations[self].id
        ):
            return False
        return self._is_new_potential_line_extra(potential_line)

    def _create_new_waves_for_lines(
        self, picking_type, potential_lines, nearest_parent_locations
    ):
        self.check_singleton()
        potential_lines = potential_lines.sorted(
            key=lambda l: (l.picking_id.id, l.move_id.id)
        )

        while potential_lines:
            potential_lines -= potential_lines.filtered(lambda l: l.batch_id.is_wave)
            if not potential_lines:
                break
            wave_lines = potential_lines._select_lines_for_one_wave(picking_type)
            if not wave_lines:
                potential_lines -= potential_lines[:1]
                continue
            new_wave = self.env["stock.picking.batch"].create(
                {
                    "is_wave": True,
                    "picking_type_id": picking_type.id,
                    "description": self._get_auto_wave_description(
                        nearest_parent_locations[self]
                    ),
                }
            )
            wave_lines._add_to_wave(new_wave)
            potential_lines -= wave_lines

    def _select_lines_for_one_wave(self, picking_type):
        probe = self.env["stock.picking.batch"].new(
            {"is_wave": True, "picking_type_id": picking_type.id}
        )
        wave_move_ids = set()
        wave_picking_ids = set()
        wave_weight = 0
        wave_line_ids = OrderedSet()
        for line in self:
            wave_move_ids.add(line.move_id.id)
            wave_picking_ids.add(line.picking_id.id)
            wave_weight += line.product_id.weight * line.quantity_product_uom
            if not probe._is_auto_mergeable(
                moves=len(wave_move_ids),
                pickings=len(wave_picking_ids),
                weight=wave_weight,
            ):
                break
            wave_line_ids.add(line.id)
        return self.browse(wave_line_ids)

    def _auto_wave_lines_into_new_waves(self, nearest_parent_locations=False):
        for picking_type, lines in self.grouped(lambda l: l.picking_type_id).items():
            potential_lines, lines_nearest_parent_locations = (
                self._get_potential_new_wave_lines(picking_type, lines)
            )

            line_to_lines = defaultdict(set)
            matched_lines = set()
            remaining_line_ids = OrderedSet()
            for line in lines:
                lines_found = False
                if line.id in matched_lines:
                    continue
                for potential_line in potential_lines:
                    if not line._is_new_wave_grouping_compatible(
                        potential_line,
                        picking_type,
                        lines_nearest_parent_locations,
                        nearest_parent_locations,
                    ):
                        continue

                    line_to_lines[line].add(potential_line.id)
                    matched_lines.add(potential_line.id)
                    lines_found = True
                if not lines_found:
                    remaining_line_ids.add(line.id)

            for line, potential_line_ids in line_to_lines.items():
                if line.batch_id.is_wave:
                    continue
                line._create_new_waves_for_lines(
                    picking_type,
                    self.env["stock.move.line"].browse(potential_line_ids | {line.id}),
                    nearest_parent_locations,
                )

            remaining_lines = self.env["stock.move.line"].browse(remaining_line_ids)
            remaining_waves = self.env["stock.picking.batch"].create(
                [
                    {
                        "is_wave": True,
                        "picking_type_id": picking_type.id,
                        "description": remaining_line._get_auto_wave_description(
                            nearest_parent_locations[remaining_line]
                        ),
                    }
                    for remaining_line in remaining_lines
                ]
            )
            for line, wave in zip(remaining_lines, remaining_waves, strict=True):
                line._add_to_wave(wave)

    def _get_auto_wave_description(self, nearest_parent_location=False):
        self.check_singleton()
        picking_type = self.picking_type_id
        description = self.picking_id._get_auto_batch_description()
        description_items = [description] if description else []
        wave_criteria = picking_type._get_active_grouping_criteria(
            picking_type._get_wave_grouping_criteria()
        )
        for criterion in wave_criteria.values():
            value = self.mapped(criterion.line_path)
            if value:
                description_items.append(value[criterion.label_field])
        if picking_type.wave_group_by_location and nearest_parent_location:
            description_items.append(nearest_parent_location.complete_name)

        return ", ".join(description_items)
