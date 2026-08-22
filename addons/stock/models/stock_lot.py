import re
from collections import Counter, defaultdict
from collections.abc import Iterable

from odoo import _, api, fields, models
from odoo.exceptions import UserError, ValidationError
from odoo.fields import Domain

from odoo.addons.stock.const import PY_OPERATORS


class StockLot(models.Model):
    _name = "stock.lot"
    _inherit = ["mixin.mail.thread", "mixin.mail.activity"]
    _description = "Lot/Serial"
    _check_company_auto = True
    _order = "name, id"

    name = fields.Char(
        string="Lot/Serial Number",
        required=True,
        compute="_compute_name",
        store=True,
        precompute=True,
        readonly=False,
        index="trigram",
        help="Unique Lot/Serial Number",
    )
    active = fields.Boolean(default=True)
    ref = fields.Char(
        string="Internal Reference",
        help="Internal reference number in case it differs from the manufacturer's lot/serial number",
    )
    product_id = fields.Many2one(
        comodel_name="product.product",
        string="Product",
        required=True,
        check_company=True,
        domain=(
            "[('tracking', '!=', 'none'), ('is_storable', '=', True)] +"
            " ([('product_tmpl_id', '=', context['default_product_tmpl_id'])] if context.get('default_product_tmpl_id') else [])"
        ),
        index=True,
        tracking=True,
    )
    product_uom_id = fields.Many2one(
        related="product_id.uom_id",
        comodel_name="uom.uom",
        string="Unit",
    )
    company_id = fields.Many2one(
        comodel_name="res.company",
        string="Company",
        compute="_compute_company_id",
        store=True,
        readonly=False,
        index=True,
    )
    note = fields.Html(string="Description")
    display_complete = fields.Boolean(compute="_compute_display_complete")
    quant_ids = fields.One2many(
        comodel_name="stock.quant",
        inverse_name="lot_id",
        string="Quants",
        readonly=True,
    )
    product_qty = fields.Float(
        string="On Hand Quantity",
        compute="_compute_product_qty",
        search="_search_product_qty",
    )
    delivery_ids = fields.Many2many(
        comodel_name="stock.picking",
        string="Transfers",
        compute="_compute_delivery_ids",
    )
    count_transfer_outgoing = fields.Count(
        "delivery_ids",
        string="Delivery order count",
    )
    partner_ids = fields.Many2many(
        comodel_name="res.partner",
        compute="_compute_partner_ids",
        search="_search_partner_ids",
    )
    lot_properties = fields.Properties(
        string="Properties",
        definition="product_id.lot_properties_definition",
        copy=True,
    )
    location_id = fields.Many2one(
        comodel_name="stock.location",
        string="Location",
        compute="_compute_location_id",
        store=True,
        readonly=False,
        inverse="_inverse_location_id",
        domain="[('usage', '!=', 'view')]",
        group_expand="_read_group_location_id",
    )

    _name_product_company_uniq = models.Constraint(
        "UNIQUE NULLS NOT DISTINCT (name, product_id, company_id)",
        "The combination of lot/serial number and product must be unique within a company.",
    )

    @api.constrains("name", "product_id", "company_id")
    def _check_unique_lot(self):
        domain = [
            ("product_id", "in", self.product_id.ids),
            ("name", "in", self.mapped("name")),
        ]
        groupby = ["company_id", "product_id", "name"]
        if any(not lot.company_id for lot in self):
            self = self.sudo()
        records = self.with_context(skip_preprocess_gs1=True)._read_group(
            domain,
            groupby,
            ["__count"],
        )
        cross_lots = {}
        for company, product, name, count in records:
            if not company:
                cross_lots[(product, name)] = count
        duplicate_pairs = set()
        for company, product, name, count in records:
            duplicates = count
            if company:
                duplicates += cross_lots.get((product, name), 0)
            if duplicates > 1:
                duplicate_pairs.add((product, name))
        if duplicate_pairs:
            self._raise_duplicate_lot_error(duplicate_pairs)

    @api.model
    def _raise_duplicate_lot_error(self, product_name_pairs):
        error_message_lines = sorted(
            _(
                " - Product: %(product)s, Lot/Serial Number: %(lot)s",
                product=product.display_name,
                lot=name,
            )
            for product, name in product_name_pairs
        )
        raise ValidationError(
            _(
                "The combination of lot/serial number and product must be unique within a company including when no company is defined.\nThe following combinations contain duplicates:\n%(error_lines)s",
                error_lines="\n".join(error_message_lines),
            ),
        )

    @api.model
    def _check_duplicate_lot_keys(self, keys, exclude_ids=None):
        keys = [key for key in keys if key[0] and key[1]]
        if not keys:
            return
        duplicates = {key for key, count in Counter(keys).items() if count > 1}
        remaining = set(keys) - duplicates
        if remaining:
            domain = [
                ("product_id", "in", [key[0] for key in remaining]),
                ("name", "in", [key[1] for key in remaining]),
            ]
            if exclude_ids:
                domain.append(("id", "not in", list(exclude_ids)))
            groups = (
                self.sudo()
                .with_context(skip_preprocess_gs1=True)
                ._read_group(domain, ["product_id", "name", "company_id"], ["__count"])
            )
            existing = {
                (product.id, name, company.id if company else False)
                for product, name, company, __ in groups
            }
            duplicates |= remaining & existing
        if duplicates:
            products = self.env["product.product"].browse(
                {product_id for product_id, __, __ in duplicates}
            )
            product_by_id = {product.id: product for product in products}
            self._raise_duplicate_lot_error(
                {
                    (product_by_id[product_id], name)
                    for product_id, name, __ in duplicates
                }
            )

    @api.model_create_multi
    def create(self, vals_list):
        lot_product_ids = {val.get("product_id") for val in vals_list} | {
            self.env.context.get("default_product_id")
        }
        lot_product_ids.discard(None)
        lot_product_ids.discard(False)
        self.with_context(lot_product_ids=lot_product_ids)._check_create()
        self._check_duplicate_lot_keys(
            (
                vals.get("product_id"),
                vals.get("name"),
                vals.get("company_id") or False,
            )
            for vals in vals_list
        )
        return super(StockLot, self.with_context(mail_create_nosubscribe=True)).create(
            vals_list
        )

    def write(self, vals):
        if any(field in vals for field in ("name", "product_id", "company_id")):
            self._check_duplicate_lot_keys(
                [
                    (
                        vals.get("product_id", lot.product_id.id),
                        vals.get("name", lot.name),
                        vals.get("company_id", lot.company_id.id) or False,
                    )
                    for lot in self
                ],
                exclude_ids=self.ids,
            )
        if vals.get("company_id"):
            for lot in self:
                quant_companies = lot.quant_ids.filtered(
                    lambda q: q.quantity
                ).location_id.company_id
                if any(company.id != vals["company_id"] for company in quant_companies):
                    raise UserError(
                        _(
                            "You cannot change the company of a lot/serial number currently in a location belonging to another company."
                        ),
                    )
        if "product_id" in vals and any(
            vals["product_id"] != lot.product_id.id for lot in self
        ):
            move_lines = self.env["stock.move.line"].search(
                [("lot_id", "in", self.ids), ("product_id", "!=", vals["product_id"])]
            )
            if move_lines:
                raise UserError(
                    _(
                        "You are not allowed to change the product linked to a serial or lot number "
                        "if some stock moves have already been created with that number. "
                        "This would lead to inconsistencies in your stock."
                    ),
                )
        return super().write(vals)

    def copy_data(self, default=None):
        default = dict(default or {})
        vals_list = super().copy_data(default=default)
        if "name" not in default:
            for lot, vals in zip(self, vals_list, strict=True):
                vals["name"] = _("(copy of) %s", lot.name)
        return vals_list

    @api.model
    def default_get(self, fields):
        context = dict(self.env.context)
        context.pop("default_company_id", False)
        return super(StockLot, self.with_context(context)).default_get(fields)

    def _compute_delivery_ids(self):
        delivery_ids_by_lot = self._get_delivery_ids_by_lot()
        for lot in self:
            lot.delivery_ids = delivery_ids_by_lot.get(lot.id, [])

    def _compute_partner_ids(self):
        for lot in self:
            pickings = lot.delivery_ids.sorted(key="date_done", reverse=True)
            lot.partner_ids = self._get_partners_from_deliveries(pickings)

    @api.depends("product_id")
    def _compute_name(self):
        for lot in self:
            if lot.name:
                continue
            if lot.product_id.lot_name_format:
                lot.name = lot._prepare_name()
                continue
            lot.name = (
                lot.product_id.lot_sequence_id.next_by_id()
                if lot.product_id.lot_sequence_id
                else self.env["ir.sequence"].next_by_code("stock.lot.serial")
            )

    @api.model
    def _get_lot_name_placeholders(self) -> dict[str, str]:
        return dict(
            self.env["ir.sequence"]._get_pattern_placeholders(),
            ref=r".+?",
        )

    def _get_lot_name_values(self) -> dict:
        self.ensure_one()
        now = fields.Datetime.context_timestamp(self, fields.Datetime.now())
        formats = self.env["ir.sequence"]._get_interpolation_formats()
        values = {name: now.strftime(fmt) for name, fmt in formats.items()}
        values["ref"] = self.ref or (
            self.product_id.lot_sequence_id.next_by_id()
            if self.product_id.lot_sequence_id
            else self.env["ir.sequence"].next_by_code("stock.lot.serial")
        )
        return values

    def _prepare_name(self) -> str:
        self.ensure_one()
        return self.product_id.lot_name_format % self._get_lot_name_values()

    def _parse_name(self, name=None):
        self.ensure_one()
        lot_format = self.product_id.lot_name_format
        name = self.name if name is None else name
        if not lot_format or not name:
            return None
        regex = self.env["ir.sequence"]._pattern_to_regex(
            lot_format, self._get_lot_name_placeholders()
        )
        match = re.match(regex, name)
        return match.groupdict() if match else None

    @api.depends("product_id.company_id")
    def _compute_company_id(self):
        for lot in self:
            if (
                self.env.company in lot.product_id.company_id.all_child_ids
                and lot.product_id.company_id not in self.env.companies
            ):
                lot.company_id = self.env.company
            else:
                lot.company_id = lot.product_id.company_id

    @api.depends("name")
    def _compute_display_complete(self):
        for prod_lot in self:
            prod_lot.display_complete = prod_lot.id or self.env.context.get(
                "display_complete"
            )

    @api.depends("quant_ids", "quant_ids.quantity")
    def _compute_location_id(self):
        for lot in self:
            quants = lot.quant_ids.filtered(
                lambda q: q.product_uom_id.compare(q.quantity, 0) > 0
            )
            lot.location_id = (
                quants.location_id if len(quants.location_id) == 1 else False
            )

    @api.depends_context(
        "owner_id",
        "package_id",
        "to_date",
        "location",
        "warehouse_id",
        "search_location",
        "search_warehouse",
        "allowed_company_ids",
    )
    @api.depends("quant_ids", "quant_ids.quantity")
    def _compute_product_qty(self):
        qty_by_lot = self._get_product_qty_by_lot(Domain("lot_id", "in", self.ids))
        for lot in self:
            lot.product_qty = qty_by_lot.get(lot, 0.0)

    def _inverse_location_id(self):
        for lot in self:
            quants = lot.quant_ids.filtered(
                lambda q: q.product_uom_id.compare(q.quantity, 0) > 0
            )
            if len(quants.location_id) == 1:
                unpack = len(quants.package_id.quant_ids) > 1
                quants.move_quants(
                    location_dest_id=lot.location_id,
                    message=_("Lot/Serial Number Relocated"),
                    unpack=unpack,
                )
            elif len(quants.location_id) > 1:
                raise UserError(
                    _(
                        "You can only move a lot/serial to a new location if it exists in a single location."
                    ),
                )

    def _search_product_qty(self, operator, value):
        op = PY_OPERATORS.get(operator)
        if not op:
            return NotImplemented
        if isinstance(value, Iterable) and not isinstance(value, str):
            value = {float(v) for v in value}
        else:
            value = float(value)
        qty_by_lot = self._get_product_qty_by_lot(Domain("lot_id", "!=", False))
        ids = [lot.id for lot, qty in qty_by_lot.items() if op(qty, value)]

        if op(0.0, value):
            lots_w_qty = [lot.id for lot in qty_by_lot]
            return ["|", ("id", "in", ids), ("id", "not in", lots_w_qty)]
        return [("id", "in", ids)]

    def _search_partner_ids(self, operator, value):
        if operator in Domain.NEGATIVE_OPERATORS or not isinstance(value, (Iterable)):
            return NotImplemented
        is_no_partner = operator == "in" and list(value) == [False]
        domain = Domain(
            [
                ("lot_id", "!=", False),
                ("state", "=", "done"),
            ]
        )
        if is_no_partner:
            domain &= Domain("picking_partner_id", "!=", False) | Domain(
                "move_partner_id", "!=", False
            )
        else:
            domain &= Domain.OR(
                [
                    Domain("picking_partner_id", operator, value),
                    Domain("move_partner_id", operator, value),
                ]
            )
        domain &= Domain(self._get_outgoing_domain())
        move_lines = self.env["stock.move.line"].search(domain)

        if is_no_partner:
            return [("id", "not in", move_lines.lot_id.ids)]
        return [("id", "in", move_lines.lot_id.ids)]

    def action_lot_open_quants(self):
        self.ensure_one()
        self = self.with_context(search_default_lot_id=self.id, create=False)
        if self.env.user.has_group("stock.group_stock_manager"):
            self = self.with_context(inventory_mode=True)
        return self.env["stock.quant"].action_view_quants()

    def action_lot_open_transfers(self):
        self.ensure_one()

        action = {"res_model": "stock.picking", "type": "ir.actions.act_window"}
        if len(self.delivery_ids) == 1:
            action.update({"view_mode": "form", "res_id": self.delivery_ids[0].id})
        else:
            action.update(
                {
                    "name": _("Delivery orders of %s", self.display_name),
                    "domain": [("id", "in", self.delivery_ids.ids)],
                    "view_mode": "list,form",
                }
            )
        return action

    def _read_group_location_id(self, locations, domain):
        partner_locations = locations.search(
            [("usage", "in", ("customer", "supplier"))]
        )
        return partner_locations + locations.warehouse_id.search([]).lot_stock_id

    @api.model
    def generate_lot_names(self, first_lot, count):
        caught_initial_number = re.findall(r"\d+", first_lot)
        if not caught_initial_number:
            return self.generate_lot_names(first_lot + "0", count)
        initial_number = caught_initial_number[-1]
        padding = len(initial_number)
        splitted = re.split(initial_number, first_lot)
        prefix = initial_number.join(splitted[:-1])
        suffix = splitted[-1]
        initial_number = int(initial_number)

        return [
            {
                "lot_name": "%s%s%s"
                % (prefix, str(initial_number + i).zfill(padding), suffix),
            }
            for i in range(count)
        ]

    @api.model
    def _get_next_serial(self, company, product):
        if product.tracking != "none":
            last_serial = self.search(
                [
                    "|",
                    ("company_id", "=", company.id),
                    ("company_id", "=", False),
                    ("product_id", "=", product.id),
                ],
                limit=1,
                order="id DESC",
            )
            if last_serial:
                return self.generate_lot_names(last_serial.name, 2)[1]["lot_name"]
        return False

    def _get_partners_from_deliveries(self, pickings):
        return pickings.partner_id

    def _get_product_qty_by_lot(self, lot_domain):
        domain_quant_loc, domain_move_in_loc, domain_move_out_loc = (
            self.env["product.product"]
            .with_context(skip_in_progress=True)
            ._get_domain_locations()
        )
        owner_id = self.env.context.get("owner_id")
        package_id = self.env.context.get("package_id")
        to_date = fields.Datetime.to_datetime(self.env.context.get("to_date"))
        dates_in_the_past = to_date and to_date < fields.Datetime.now()

        domain_quant = lot_domain & domain_quant_loc
        if owner_id is not None:
            domain_quant &= Domain("owner_id", "=", owner_id)
            domain_move_in_loc &= Domain("owner_id", "=", owner_id)
            domain_move_out_loc &= Domain("owner_id", "=", owner_id)
        if package_id is not None:
            domain_quant &= Domain("package_id", "=", package_id)
            domain_move_in_loc &= Domain("result_package_id", "=", package_id)
            domain_move_out_loc &= Domain("package_id", "=", package_id)
        qty_by_lot = dict(
            self.env["stock.quant"]._read_group(
                domain_quant, ["lot_id"], ["quantity:sum"]
            )
        )
        if not dates_in_the_past:
            return qty_by_lot

        domain_lot_done = lot_domain & Domain(
            [("state", "=", "done"), ("move_id.date", ">", to_date)]
        )
        move_in_qty_by_lot = dict(
            self.env["stock.move.line"]._read_group(
                domain_move_in_loc & domain_lot_done,
                ["lot_id"],
                ["quantity_product_uom:sum"],
            )
        )
        move_out_qty_by_lot = dict(
            self.env["stock.move.line"]._read_group(
                domain_move_out_loc & domain_lot_done,
                ["lot_id"],
                ["quantity_product_uom:sum"],
            )
        )
        return {
            lot: qty_by_lot.get(lot, 0.0)
            - move_in_qty_by_lot.get(lot, 0.0)
            + move_out_qty_by_lot.get(lot, 0.0)
            for lot in set(qty_by_lot)
            | set(move_in_qty_by_lot)
            | set(move_out_qty_by_lot)
        }

    @api.model
    def _get_outgoing_domain(self):
        return [
            "|",
            "|",
            ("picking_code", "=", "outgoing"),
            ("move_id.picking_code", "=", "outgoing"),
            ("produce_line_ids", "!=", False),
        ]

    def _get_delivery_ids_by_lot(self):
        all_lot_ids = set(self.ids)
        barren_lines = defaultdict(set)
        parent_map = defaultdict(set)

        queue = list(self.ids)
        while queue:
            domain = Domain(
                [
                    ("lot_id", "in", queue),
                    ("state", "=", "done"),
                ]
            ) & Domain(self._get_outgoing_domain())

            queue = []
            move_lines = self.env["stock.move.line"].search(domain)
            for line in move_lines:
                lot_id = line.lot_id.id

                produce_line_lot_ids = line.produce_line_ids.lot_id.ids
                if produce_line_lot_ids:
                    for child_lot_id in produce_line_lot_ids:
                        parent_map[child_lot_id].add(lot_id)
                else:
                    barren_lines[lot_id].add(line.id)

                next_lots = set(produce_line_lot_ids) - all_lot_ids
                all_lot_ids.update(next_lots)
                queue.extend(next_lots)

        lots_to_propagate = set()
        delivery_by_lot = {lot_id: set() for lot_id in all_lot_ids}
        for lot_id in barren_lines:
            barren_line_ids = barren_lines[lot_id]
            if barren_line_ids:
                barren_move_lines = self.env["stock.move.line"].browse(barren_line_ids)
                delivery_by_lot[lot_id].update(barren_move_lines.picking_id.ids)
                lots_to_propagate.add(lot_id)

        while lots_to_propagate:
            lot_id = lots_to_propagate.pop()

            for parent_id in parent_map.get(lot_id, []):
                new_deliveries = delivery_by_lot[lot_id] - delivery_by_lot[parent_id]
                if new_deliveries:
                    delivery_by_lot[parent_id].update(new_deliveries)
                    lots_to_propagate.add(parent_id)

        return {lot_id: list(delivery_by_lot[lot_id]) for lot_id in delivery_by_lot}

    @api.model
    def _get_accessible_location_domain(self):
        return [
            "|",
            ("location_id", "=", False),
            (
                "location_id",
                "any",
                self.env["stock.location"]._check_company_domain(
                    self.env.context.get("allowed_company_ids")
                    or self.env.companies.ids
                ),
            ),
        ]

    def _check_create(self):
        active_picking_id = self.env.context.get("active_picking_id", False)
        if active_picking_id:
            picking_id = self.env["stock.picking"].browse(active_picking_id)
            if picking_id and not picking_id.picking_type_id.use_create_lots:
                raise UserError(
                    _(
                        'You are not allowed to create a lot or serial number with this operation type. To change this, go on the operation type and tick the box "Create New Lots/Serial Numbers".'
                    ),
                )
