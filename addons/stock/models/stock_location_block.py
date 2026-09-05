import logging
from collections import defaultdict

from markupsafe import Markup

from odoo import api, fields, models
from odoo.exceptions import UserError
from odoo.fields import Domain

from ..const import (
    BLOCK_GOVERNED_FIELDS,
    BLOCK_REASON_OVERRIDE_HARD,
    BLOCK_REASON_OVERRIDE_SOFT,
    CONTEXT_BLOCK_BYPASS,
    CONTEXT_BLOCK_COMPLETING,
    CONTEXT_BLOCK_IS_INVENTORY,
    CONTEXT_BLOCK_SKIP_HOOKS,
    INCOMING_BLOCK_TYPES,
    INTERNAL_CONTEXT_FLAG,
    OUTGOING_BLOCK_TYPES,
    is_internal_flag,
)
from .stock_location import (
    GROUP_FORCE_BLOCK_IN,
    GROUP_FORCE_BLOCK_OUT,
    GROUP_OVERRIDE_HARD_BLOCK,
    GROUP_STOCK_USER,
    merge_block_types,
)
from odoo.addons.stock.tools.quantity import get_context_record_ids

_logger = logging.getLogger(__name__)


class StockLocationBlock(models.Model):
    _inherit = "stock.location"

    @api.depends("block_type", "location_id.effective_block_type")
    def _compute_effective_block_type(self):
        for location in self:
            location.effective_block_type = merge_block_types(
                *location._get_block_types_self_and_ancestors(),
            )

    def _get_block_types_self_and_ancestors(self):
        self.check_singleton()
        block_types = []
        location = self
        seen = set()
        while location and location.id not in seen:
            seen.add(location.id)
            block_types.append(location.block_type)
            location = location.location_id
        return block_types

    @api.model
    def _get_block_type_label(self, block_type):
        return dict(
            self._fields["block_type"]._description_selection(self.env),
        )[block_type or "none"]

    def _get_block_decision(self, direction):
        self.check_singleton()
        if direction not in ("in", "out"):
            raise ValueError(f"direction must be 'in' or 'out', got {direction!r}")

        effective = self.effective_block_type or "none"
        block_set = INCOMING_BLOCK_TYPES if direction == "in" else OUTGOING_BLOCK_TYPES
        if effective not in block_set:
            return True, None

        env = self.env
        if env.su:
            return True, None
        if effective == "hard":
            if env.user.has_group(GROUP_OVERRIDE_HARD_BLOCK):
                return True, BLOCK_REASON_OVERRIDE_HARD
            return False, None
        if env["stock.quant"]._is_inventory_mode() or (
            is_internal_flag(env.context, CONTEXT_BLOCK_IS_INVENTORY)
            and env.user.has_group(GROUP_STOCK_USER)
        ):
            return True, None
        if direction == "out" and is_internal_flag(
            env.context, CONTEXT_BLOCK_COMPLETING
        ):
            return True, None
        group = GROUP_FORCE_BLOCK_IN if direction == "in" else GROUP_FORCE_BLOCK_OUT
        if env.user.has_group(group):
            return True, BLOCK_REASON_OVERRIDE_SOFT
        return False, None

    def _is_operation_allowed(self, direction):
        return self._get_block_decision(direction)[0]

    def _check_operation_allowed(self, direction):
        self.check_singleton()
        if self._is_operation_allowed(direction):
            return
        block_label = self._get_block_type_label(self.effective_block_type)
        if direction == "in":
            raise UserError(
                self.env._(
                    "Cannot add stock to %(location)s: the location is set to "
                    "%(block)s.",
                    location=self.display_name,
                    block=block_label,
                ),
            )
        raise UserError(
            self.env._(
                "Cannot move stock from %(location)s: the location is set to "
                "%(block)s.",
                location=self.display_name,
                block=block_label,
            ),
        )

    def _check_quantity_change_allowed(self, quantity):
        if quantity and quantity > 0:
            self._check_operation_allowed("in")
        elif quantity and quantity < 0:
            self._check_operation_allowed("out")

    def _get_block_types_excluded_from_gathering(self, reserving=False):
        env = self.env
        if env.su:
            return OUTGOING_BLOCK_TYPES if reserving else ()
        if env["stock.quant"]._is_inventory_mode():
            return ()
        if env.user.has_group(GROUP_OVERRIDE_HARD_BLOCK):
            return ()
        if env.user.has_group(GROUP_FORCE_BLOCK_OUT):
            return ("hard",)
        return OUTGOING_BLOCK_TYPES

    def _reserved_quantities_by_uom(self):
        if not self:
            return {}
        groups = self.env["stock.quant"]._read_group(
            [("location_id", "child_of", self.ids), ("reserved_quantity", ">", 0)],
            groupby=["location_id", "product_id"],
            aggregates=["reserved_quantity:sum"],
        )
        per_quant_location = {}
        for quant_location, product, reserved in groups:
            by_uom = per_quant_location.setdefault(quant_location, defaultdict(float))
            by_uom[product.uom_id] += reserved or 0.0

        totals = {location_id: defaultdict(float) for location_id in self.ids}
        paths = {location.id: location.parent_path or "" for location in self}
        for quant_location, by_uom in per_quant_location.items():
            quant_path = quant_location.parent_path or ""
            for location_id, path in paths.items():
                if path and quant_path.startswith(path):
                    for uom_name, quantity in by_uom.items():
                        totals[location_id][uom_name] += quantity
        return {location_id: dict(by_uom) for location_id, by_uom in totals.items()}

    def _total_reserved_quantities(self):
        return {
            location_id: sum(by_uom.values())
            for location_id, by_uom in self._reserved_quantities_by_uom().items()
        }

    def _check_block_governance_before_write(self, vals):
        if is_internal_flag(
            self.env.context, CONTEXT_BLOCK_SKIP_HOOKS
        ) or BLOCK_GOVERNED_FIELDS.isdisjoint(vals):
            return self.browse()
        self._check_block_governance(vals)
        if "block_type" not in vals:
            return self.browse()
        return self.filtered(
            lambda location: vals["block_type"] != (location.block_type or "none"),
        )

    def _check_block_governance_before_unlink(self):
        if self.env.su or self.env.user.has_group(GROUP_OVERRIDE_HARD_BLOCK):
            return
        blocked = self.filtered(
            lambda location: location.effective_block_type == "hard",
        )
        if blocked:
            raise UserError(
                self.env._(
                    "Deleting the hard-blocked location %(locations)s requires "
                    'the "Unlock Locations: All (Hard)" permission.',
                    locations=blocked._get_display_names_joined(),
                ),
            )

    def _check_block_governance(self, vals):
        if self.env.su or self.env.user.has_group(GROUP_OVERRIDE_HARD_BLOCK):
            return

        if "block_type" in vals and vals["block_type"] != "hard":
            lifting = self.filtered(lambda location: location.block_type == "hard")
            if lifting:
                raise UserError(
                    self.env._(
                        "Lifting a hard block on %(locations)s requires the "
                        '"Unlock Locations: All (Hard)" permission.',
                        locations=lifting._get_display_names_joined(),
                    ),
                )
        if vals.get("active") is False:
            archiving = self.filtered(
                lambda location: location.effective_block_type == "hard",
            )
            if archiving:
                raise UserError(
                    self.env._(
                        "Archiving the hard-blocked location %(locations)s "
                        'requires the "Unlock Locations: All (Hard)" permission.',
                        locations=archiving._get_display_names_joined(),
                    ),
                )
        if "location_id" in vals:
            new_parent = self.browse(vals["location_id"] or ())
            escaping = (
                self.browse()
                if new_parent.effective_block_type == "hard"
                else self.filtered(
                    lambda location: (
                        location.effective_block_type == "hard"
                        and location.block_type != "hard"
                    ),
                )
            )
            if escaping:
                raise UserError(
                    self.env._(
                        "Moving %(locations)s out from under a hard block "
                        'requires the "Unlock Locations: All (Hard)" permission.',
                        locations=escaping._get_display_names_joined(),
                    ),
                )

    def _get_display_names_joined(self):
        return ", ".join(self.mapped("display_name"))

    def _update_block_metadata(self):
        if not self:
            return
        reserved_by_location = self._reserved_quantities_by_uom()
        now = fields.Datetime.now()
        by_total = defaultdict(list)
        for location in self:
            by_total[sum(reserved_by_location[location.id].values())].append(
                location.id
            )
        for total, location_ids in by_total.items():
            self.browse(location_ids).with_context(
                **{CONTEXT_BLOCK_SKIP_HOOKS: INTERNAL_CONTEXT_FLAG},
            ).write(
                {
                    "blocked_date": now,
                    "blocked_by_user_id": self.env.uid,
                    "reserved_qty_when_blocked": total,
                },
            )
        for location in self:
            location.sudo().message_post(
                body=location._prepare_block_message_body(
                    reserved_by_location[location.id]
                ),
            )

    def _prepare_block_message_body(self, reserved_by_uom):
        self.check_singleton()
        body = Markup("<p><b>%s</b> %s</p>") % (
            self.env._("Location Blocked:"),
            self._get_block_type_label(self.block_type),
        )
        quantities = self._format_reserved_quantities(reserved_by_uom)
        if quantities:
            if self.block_type == "hard":
                body += Markup("<p>⚠️ <b>%s</b> %s</p>") % (
                    self.env._("Warning:"),
                    self.env._(
                        "%(quantities)s are currently reserved. A hard block "
                        "prevents completing these reservations — consider "
                        "unreserving the stock or using a soft block instead.",
                        quantities=quantities,
                    ),
                )
            else:
                body += Markup("<p>ℹ️ <b>%s</b> %s</p>") % (
                    self.env._("Info:"),
                    self.env._(
                        "%(quantities)s are currently reserved. Existing "
                        "reservations will be allowed to complete.",
                        quantities=quantities,
                    ),
                )
        if self.block_reason:
            body += Markup("<p><b>%s</b> %s</p>") % (
                self.env._("Reason:"),
                self.block_reason,
            )
        return body

    @api.model
    def _format_reserved_quantities(self, reserved_by_uom):
        return ", ".join(
            f"{quantity:.2f} {uom.name}"
            for uom, quantity in sorted(
                reserved_by_uom.items(), key=lambda item: item[0].name or ""
            )
            if quantity > 0
        )

    def _remove_block_metadata(self):
        if not self:
            return
        self.with_context(
            **{CONTEXT_BLOCK_SKIP_HOOKS: INTERNAL_CONTEXT_FLAG},
        ).write(
            {
                "blocked_date": False,
                "blocked_by_user_id": False,
                "reserved_qty_when_blocked": 0.0,
                "block_reason": False,
            },
        )
        body = Markup("<b>%s</b>") % self.env._("Location Unblocked")
        for location in self:
            location.sudo().message_post(body=body)

    def action_unreserve_stock(self):
        self.check_singleton()

        if self.effective_block_type != "hard":
            return {
                "type": "ir.actions.client",
                "tag": "display_notification",
                "params": {
                    "title": self.env._("Not a Hard Block"),
                    "message": self.env._(
                        "Unreserving is only available for hard-blocked locations."
                    ),
                    "type": "warning",
                },
            }

        if not self.env.su and not self.env.user.has_group(GROUP_OVERRIDE_HARD_BLOCK):
            raise UserError(
                self.env._(
                    "Clearing the reservations of the hard-blocked location "
                    '%(location)s requires the "Unlock Locations: All (Hard)" '
                    "permission.",
                    location=self.display_name,
                ),
            )

        self._unreserve_all_stock()

        return {
            "type": "ir.actions.client",
            "tag": "display_notification",
            "params": {
                "title": self.env._("Stock Unreserved"),
                "message": self.env._(
                    "All reservations in this location have been cleared."
                ),
                "type": "success",
                "next": {"type": "ir.actions.client", "tag": "soft_reload"},
            },
        }

    def _unreserve_all_stock(self):
        self.check_singleton()

        move_lines = self.env["stock.move.line"].search(
            [
                ("location_id", "child_of", self.id),
                ("state", "not in", ("done", "cancel", "draft")),
                ("quantity_product_uom", ">", 0),
            ],
        )
        if not move_lines:
            return

        moves = move_lines.move_id
        line_count = len(move_lines)
        move_count = len(moves)
        moves._unreserve()

        self.sudo().message_post(
            body=Markup("<b>%s</b><br/>%s")
            % (
                self.env._("Hard Block Auto-Unreserve:"),
                self.env._(
                    "Unreserved %(line_count)d stock move line(s) across "
                    "%(move_count)d move(s).",
                    line_count=line_count,
                    move_count=move_count,
                ),
            ),
        )

    def _get_domains_quantity_from_context(self) -> tuple[Domain, Domain, Domain]:
        location_ids = self._resolve_scope_ids_from_context()
        fell_back = location_ids is None
        if fell_back:
            location_ids = set(
                self.env["stock.warehouse"]
                .search([("company_id", "in", self.env.companies.ids)])
                .mapped("view_location_id")
                .ids
            )
        if _logger.isEnabledFor(logging.DEBUG):
            context = self.env.context
            _logger.debug(
                "quantity scope: locations=%s%s from %s, companies=%s",
                sorted(location_ids) or "NONE (every domain is FALSE)",
                " (fallback: no scope in the context)" if fell_back else "",
                {
                    key: context[key]
                    for key in (
                        "location",
                        "search_location",
                        "warehouse_id",
                        "search_warehouse",
                        "strict",
                        "skip_in_progress",
                    )
                    if key in context
                }
                or "no scope keys",
                self.env.companies.ids,
            )
        return self._get_domains_quantity(location_ids)

    def _resolve_scope_ids_from_context(self) -> set[int] | None:
        context = self.env.context
        location = context.get("location") or context.get("search_location")
        if location and not isinstance(location, list):
            location = [location]
        warehouse = context.get("warehouse_id") or context.get("search_warehouse")
        if warehouse and not isinstance(warehouse, list):
            warehouse = [warehouse]

        if not warehouse:
            if not location:
                return None
            return get_context_record_ids(self.env, "stock.location", location)

        view_location_ids = set(
            self.env["stock.warehouse"]
            .browse(
                get_context_record_ids(self.env, "stock.warehouse", warehouse),
            )
            .mapped("view_location_id")
            .ids
        )
        if not location:
            return view_location_ids
        views = set(view_location_ids)
        return {
            candidate.id
            for candidate in self.browse(
                get_context_record_ids(self.env, "stock.location", location),
            )
            if views & set(candidate._ancestor_ids(include_self=True))
        }

    def _get_domains_move_destination(self, leaf) -> tuple[Domain, Domain]:
        done = leaf("location_dest_id")
        if self.env.context.get("skip_in_progress"):
            return done, ~done
        in_progress = Domain(
            [
                "|",
                "&",
                ("location_final_id", "!=", False),
                leaf("location_final_id"),
                "&",
                ("location_final_id", "=", False),
                leaf("location_dest_id"),
            ],
        )
        return (
            Domain(
                [
                    "|",
                    "&",
                    ("state", "=", "done"),
                    done,
                    "&",
                    ("state", "!=", "done"),
                    in_progress,
                ],
            ),
            Domain(
                [
                    "|",
                    "&",
                    ("state", "=", "done"),
                    ~done,
                    "&",
                    ("state", "!=", "done"),
                    ~in_progress,
                ],
            ),
        )

    def _get_domains_quantity(self, location_ids) -> tuple[Domain, Domain, Domain]:
        if not location_ids:
            return (Domain.FALSE,) * 3
        location_ids = list(location_ids)
        if self.env.context.get("strict"):
            loc_domain = Domain("location_id", "in", location_ids)
            dest_in = Domain("location_dest_id", "in", location_ids)
            dest_out = Domain("location_dest_id", "not in", location_ids)
        else:
            loc_domain = Domain("location_id", "child_of", location_ids)
            dest_in, dest_out = self._get_domains_move_destination(
                lambda field: Domain(field, "child_of", location_ids),
            )
        return self._get_domains_quantity_unblocked(
            (
                loc_domain,
                dest_in & ~loc_domain,
                loc_domain & dest_out,
            ),
        )

    def _get_domains_quantity_unblocked(self, domains):
        if self.env.user.has_group(GROUP_STOCK_USER):
            return domains
        if self.env.su and self.env.context.get(CONTEXT_BLOCK_BYPASS):
            return domains
        domain_quant, domain_move_in, domain_move_out = domains
        blocked = Domain("effective_block_type", "in", OUTGOING_BLOCK_TYPES)
        blocked_location = Domain("location_id", "any", blocked)
        blocked_destination, __ = self._get_domains_move_destination(
            lambda field: Domain(field, "any", blocked),
        )
        return (
            domain_quant & ~blocked_location,
            domain_move_in & ~blocked_destination,
            domain_move_out & ~blocked_location,
        )
