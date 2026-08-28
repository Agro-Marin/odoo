from collections import defaultdict

from odoo import Command, _, fields, models
from odoo.fields import Domain
from odoo.tools.misc import OrderedSet


class StockMoveLine(models.Model):
    _inherit = "stock.move.line"

    batch_id = fields.Many2one(related="picking_id.batch_id")

    def action_open_add_to_wave(self):
        # This action can be called from the move line list view or from the 'Add to wave' wizard
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
        """Return the create values splitting `picking` for `wave`.

        When every line and move of the picking goes to the wave there is
        nothing to split: the picking itself is linked to the wave and None is
        returned.

        :param recordset wave: The wave the lines are going to
        :param recordset picking: The picking the lines come from
        :param recordset lines: The lines of `picking` going to the wave
        :return: The picking create values, or None when the whole picking moved
        :rtype: dict | None
        """
        line_by_move = defaultdict(lambda: self.env["stock.move.line"])
        qty_by_move = defaultdict(float)
        for line in lines:
            move = line.move_id
            line_by_move[move] |= line
            qty = line.product_uom_id._compute_quantity(
                line.quantity, line.product_id.uom_id, rounding_method="HALF-UP"
            )
            qty_by_move[line.move_id] += qty

        # If all moves are to be transferred to the wave, link the picking to the wave
        if lines == picking.move_line_ids and lines.move_id == picking.move_ids:
            add_all_moves = True
            for move, qty in qty_by_move.items():
                if move.product_uom_id.is_zero(qty):
                    add_all_moves = False
                    break
            if add_all_moves:
                wave.picking_ids = [Command.link(picking.id)]
                return None

        # Split the picking in two part to extract only line that are taken on the wave
        picking_to_wave_vals = picking.copy_data(
            {
                "move_ids": [],
                "move_line_ids": [],
                "batch_id": wave.id,
                "date_planned": picking.date_planned,
            }
        )[0]
        # Every line going to the wave moves to the new picking, once. The moves
        # are what differ below: one is relinked whole, the next is split.
        picking_to_wave_vals["move_line_ids"] += [
            Command.link(line.id) for line in lines
        ]
        for move, move_lines in line_by_move.items():
            # if all the line of a stock move are taken we change the picking on the stock move
            if move_lines == move.move_line_ids:
                picking_to_wave_vals["move_ids"] += [Command.link(move.id)]
                continue
            # Split the move
            qty = qty_by_move[move]
            new_move = move._split(qty)
            new_move[0]["move_line_ids"] = [Command.set(move_lines.ids)]
            picking_to_wave_vals["move_ids"] += [Command.create(new_move[0])]

        return picking_to_wave_vals

    def _get_add_to_wave_action(self, wave, notification_title):
        """Return the client action closing the 'Add to Wave' flow.

        :param recordset wave: The wave that was created or updated
        :param str notification_title: What to say happened to it
        :return: The client action
        :rtype: dict
        """
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
        """Detach lines (and corresponding stock move from a picking to another). If wave is
        passed, attach the new picking into it; otherwise create a new wave and attach it there.

        :param recordset wave: stock.picking.batch record on which to put the move lines."""

        if not wave:
            wave = self.env["stock.picking.batch"].create(
                {
                    "is_wave": True,
                    "picking_type_id": self.picking_type_id
                    and self.picking_type_id[0].id,
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
        if wave.picking_type_id.batch_auto_confirm:
            wave.action_confirm()
        return self._get_add_to_wave_action(wave, notification_title)

    def _is_auto_waveable(self):
        self.ensure_one()
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
        """Try to find compatible waves to attach the move lines to, otherwise create new waves when possible/appropriate."""
        wave_locs_by_picking_type = {}
        for picking_type in self.picking_type_id:
            if not picking_type.wave_group_by_location:
                continue
            if picking_type in wave_locs_by_picking_type:
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
            # We want to find the most descendant location in the wave locations list that is a parent of the line location.
            # Since the wave locations are ordered by complete_name (from the most descendant to the most ancestor), we can iterate in reverse order.
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
        """Extend extra conditions here"""
        return domain_list

    def _get_potential_new_waves_extra_domain(self, domain_list, picking_type):
        """Extend extra conditions here"""
        return domain_list

    def _is_potential_existing_wave_extra(self, wave):
        """Extend extra conditions here"""
        return True

    def _is_new_potential_line_extra(self, potential_line):
        """Extend extra conditions here"""
        return True

    def _get_potential_existing_waves(self, picking_type, batches_to_validate_ids):
        """Return the waves `self`'s lines could be merged into.

        `self` is the subset of lines sharing `picking_type`; the grouping
        criteria the picking type declares each narrow the search.

        :param recordset picking_type: The picking type the lines share
        :param list batches_to_validate_ids: Waves to leave alone, or False
        :return: The candidate waves
        :rtype: recordset of `stock.picking.batch`
        """
        domains = [
            Domain("picking_type_id", "=", picking_type.id),
            Domain("company_id", "in", self.mapped("company_id").ids),
            Domain("is_wave", "=", True),
        ]
        if picking_type.batch_auto_confirm:
            domains.append(Domain("state", "not in", ["done", "cancel"]))
        else:
            domains.append(Domain("state", "=", "draft"))
        if picking_type.batch_group_by_partner:
            domains.append(
                Domain("picking_ids.partner_id", "in", self.move_id.partner_id.ids)
            )
        if picking_type.batch_group_by_destination:
            domains.append(
                Domain(
                    "picking_ids.partner_id.country_id",
                    "in",
                    self.move_id.partner_id.country_id.ids,
                )
            )
        if picking_type.batch_group_by_src_loc:
            domains.append(
                Domain("picking_ids.location_id", "in", self.location_id.ids)
            )
        if picking_type.batch_group_by_dest_loc:
            domains.append(
                Domain(
                    "picking_ids.location_dest_id",
                    "in",
                    self.location_dest_id.ids,
                )
            )
        if batches_to_validate_ids:
            domains.append(Domain("id", "not in", batches_to_validate_ids))
        domains = self._get_potential_existing_waves_extra_domain(domains, picking_type)

        return self.env["stock.picking.batch"].search(Domain.AND(domains))

    def _get_waves_nearest_parent_locations(self, picking_type, potential_waves):
        """Map each candidate wave to the wave location covering all its lines.

        We want to find the most descendant location in the wave locations list
        that is a parent of all the lines in each wave. We also want to exclude
        waves that have lines that are not in these locations.

        :param recordset picking_type: The picking type the lines share
        :param recordset potential_waves: The candidate waves
        :return: (wave -> location id, the waves that qualify)
        :rtype: tuple
        """
        waves_nearest_parent_locations = defaultdict(int)
        if not picking_type.wave_group_by_location:
            return waves_nearest_parent_locations, potential_waves

        valid_wave_ids = set()
        # Since the wave locations are ordered by complete_name (from the most
        # descendant to the most ancestor), we can iterate in reverse order.
        for wave in potential_waves:
            for wave_location in reversed(picking_type.wave_location_ids):
                if all(
                    loc._child_of(wave_location)
                    for loc in wave.move_line_ids.location_id
                ):
                    waves_nearest_parent_locations[wave] = wave_location.id
                    valid_wave_ids.add(wave.id)
                    break
        return (
            waves_nearest_parent_locations,
            self.env["stock.picking.batch"].browse(valid_wave_ids),
        )

    def _is_wave_grouping_compatible(
        self,
        wave,
        picking_type,
        waves_nearest_parent_locations,
        nearest_parent_locations,
    ):
        """Whether this line may join `wave` under the picking type's grouping.

        This is grouping only -- it says nothing about the wave's capacity.

        :param recordset wave: The candidate wave
        :param recordset picking_type: The picking type the lines share
        :param dict waves_nearest_parent_locations: wave -> location id
        :param dict nearest_parent_locations: line -> location
        :rtype: bool
        """
        self.ensure_one()
        return not (
            self.company_id != wave.company_id
            or (
                picking_type.batch_group_by_partner
                and self.move_id.partner_id != wave.picking_ids.partner_id
            )
            or (
                picking_type.batch_group_by_destination
                and self.move_id.partner_id.country_id
                != wave.picking_ids.partner_id.country_id
            )
            or (
                picking_type.batch_group_by_src_loc
                and self.location_id != wave.picking_ids.location_id
            )
            or (
                picking_type.batch_group_by_dest_loc
                and self.location_dest_id != wave.picking_ids.location_dest_id
            )
            or (
                picking_type.wave_group_by_product
                and self.product_id != wave.move_line_ids.product_id
            )
            or (
                picking_type.wave_group_by_category
                and self.product_id.categ_id != wave.move_line_ids.product_id.categ_id
            )
            or (
                picking_type.wave_group_by_location
                and waves_nearest_parent_locations[wave]
                != nearest_parent_locations[self].id
            )
            or not self._is_potential_existing_wave_extra(wave)
        )

    def _get_matching_existing_wave(
        self,
        potential_waves,
        picking_type,
        tallies,
        waves_nearest_parent_locations,
        nearest_parent_locations,
    ):
        """Return the first wave this line fits, updating `tallies` for it.

        `tallies` carries the moves, pickings and weight already promised to
        each wave by earlier lines of this run, which the capacity check has to
        count on top of what the wave already holds.

        :param recordset potential_waves: The candidate waves
        :param recordset picking_type: The picking type the lines share
        :param dict tallies: 'moves', 'pickings' and 'weight' per wave
        :param dict waves_nearest_parent_locations: wave -> location id
        :param dict nearest_parent_locations: line -> location
        :return: The wave the line joins, or False
        """
        self.ensure_one()
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
            # `is_line_auto_mergeable` is a method that checks if the line can be added to the wave without exceeding the limits
            # It takes as arguments the number of new moves that will be added to the wave, the number of new pickings that will be added to the wave
            # and the extra weight that will be added to the wave. So we need to check that the move/picking of the line is not already in the wave
            # so that we don't count them as new moves/pickings.
            if not wave._is_line_auto_mergeable(
                self.move_id.id not in wave_move_ids
                and self.move_id.id not in wave_new_move_ids
                and len(wave_new_move_ids) + 1,
                self.picking_id.id not in wave_picking_ids
                and self.picking_id.id not in wave_new_picking_ids
                and len(wave_new_picking_ids) + 1,
                tallies["weight"][wave]
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
        """Try to add move lines to existing waves if possible.

        :param defaultdict nearest_parent_locations: move line -> nearest parent location in the wave locations list
        :return: ids of move lines for which no appropriate wave was found
        :rtype: list"""
        remaining_lines = OrderedSet()
        batches_to_validate_ids = self.env.context.get("batches_to_validate", False)
        for picking_type, lines in self.grouped(lambda l: l.picking_type_id).items():
            if not lines:
                continue
            potential_waves = lines._get_potential_existing_waves(
                picking_type, batches_to_validate_ids
            )
            wave_to_new_lines = defaultdict(set)

            # These dictionaries are used to enforce batch max lines/transfers/weight limits
            # Each time a line is matched to a wave, we update the corresponding values
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
        """Return the lines a new wave for `lines` could also pick up.

        :param recordset picking_type: The picking type the lines share
        :param recordset lines: The lines a wave is being built around
        :return: (the candidate lines, line -> nearest wave location id)
        :rtype: tuple
        """
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
        if picking_type.batch_group_by_partner:
            domains.append(
                Domain("move_id.partner_id", "in", lines.move_id.partner_id.ids)
            )
        if picking_type.batch_group_by_destination:
            domains.append(
                Domain(
                    "move_id.partner_id.country_id",
                    "in",
                    lines.move_id.partner_id.country_id.ids,
                )
            )
        if picking_type.batch_group_by_src_loc:
            domains.append(Domain("location_id", "in", lines.location_id.ids))
        if picking_type.batch_group_by_dest_loc:
            domains.append(Domain("location_dest_id", "in", lines.location_dest_id.ids))
        if picking_type.wave_group_by_product:
            domains.append(Domain("product_id", "in", lines.product_id.ids))
        if picking_type.wave_group_by_category:
            domains.append(
                Domain("product_id.categ_id", "in", lines.product_id.categ_id.ids)
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
                    if line.location_id._child_of(location):
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
        """Whether `potential_line` belongs in the same new wave as this line.

        :param recordset potential_line: The line being considered
        :param recordset picking_type: The picking type the lines share
        :param dict lines_nearest_parent_locations: line -> location id
        :param dict nearest_parent_locations: line -> location
        :rtype: bool
        """
        self.ensure_one()
        return not (
            self.id == potential_line.id
            or self.company_id != potential_line.company_id
            or (
                picking_type.batch_group_by_partner
                and self.move_id.partner_id != potential_line.move_id.partner_id
            )
            or (
                picking_type.batch_group_by_destination
                and self.move_id.partner_id.country_id
                != potential_line.move_id.partner_id.country_id
            )
            or (
                picking_type.batch_group_by_src_loc
                and self.location_id != potential_line.location_id
            )
            or (
                picking_type.batch_group_by_dest_loc
                and self.location_dest_id != potential_line.location_dest_id
            )
            or (
                picking_type.wave_group_by_product
                and self.product_id != potential_line.product_id
            )
            or (
                picking_type.wave_group_by_category
                and self.product_id.categ_id != potential_line.product_id.categ_id
            )
            or (
                picking_type.wave_group_by_location
                and lines_nearest_parent_locations[potential_line]
                != nearest_parent_locations[self].id
            )
            or not self._is_new_potential_line_extra(potential_line)
        )

    def _create_new_waves_for_lines(
        self, picking_type, potential_lines, nearest_parent_locations
    ):
        """Fill new waves with `potential_lines` until they are all placed.

        We want to make sure that batch/wave limits specified in the picking
        type are respected. We want also to reduce picking splits as much as
        possible. So we try to group as much as possible by sorting the lines
        by picking and move.

        :param recordset picking_type: The picking type the lines share
        :param recordset potential_lines: The lines to place, this one included
        :param dict nearest_parent_locations: line -> location
        :return: None
        """
        self.ensure_one()
        potential_lines = potential_lines.sorted(
            key=lambda l: (l.picking_id.id, l.move_id.id)
        )

        while potential_lines:
            new_wave = self.env["stock.picking.batch"].create(
                {
                    "is_wave": True,
                    "picking_type_id": picking_type.id,
                    "description": self._get_auto_wave_description(
                        nearest_parent_locations[self]
                    ),
                }
            )
            wave_move_ids = set()
            wave_picking_ids = set()
            wave_weight = 0

            wave_line_ids = set()

            for potential_line in potential_lines:
                if potential_line.batch_id.is_wave:
                    continue
                wave_move_ids.add(potential_line.move_id.id)
                wave_picking_ids.add(potential_line.picking_id.id)
                wave_weight += (
                    potential_line.product_id.weight
                    * potential_line.quantity_product_uom
                )
                if new_wave._is_line_auto_mergeable(
                    len(wave_move_ids), len(wave_picking_ids), wave_weight
                ):
                    wave_line_ids.add(potential_line.id)
                else:
                    break
            wave_lines = self.env["stock.move.line"].browse(wave_line_ids)
            wave_lines._add_to_wave(new_wave)
            potential_lines -= wave_lines

    def _auto_wave_lines_into_new_waves(self, nearest_parent_locations=False):
        """Create new waves for the move lines that could not be added to existing waves."""
        picking_types = self.picking_type_id
        for picking_type in picking_types:
            lines = self.filtered(
                lambda l, picking_type=picking_type: l.picking_type_id == picking_type
            )
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
        self.ensure_one()
        description = self.picking_id._get_auto_batch_description()
        description_items = []
        if description:
            description_items.append(description)

        if self.picking_type_id.wave_group_by_product:
            description_items.append(self.product_id.display_name)
        if self.picking_type_id.wave_group_by_category:
            description_items.append(self.product_id.categ_id.complete_name)
        if self.picking_type_id.wave_group_by_location:
            description_items.append(nearest_parent_location.complete_name)

        return ", ".join(description_items)
