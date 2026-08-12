import json
from ast import literal_eval
from datetime import UTC, timedelta

from odoo import _, api, fields, models
from odoo.exceptions import UserError
from odoo.fields import Domain
from odoo.tools import SQL


class StockPickingType(models.Model):
    _name = "stock.picking.type"
    _inherit = ["mail.thread", "date.category.mixin"]
    _description = "Picking Type"
    _order = "is_favorite desc, sequence, id"
    _rec_names_search = ["name", "warehouse_id.name"]
    _check_company_auto = True


    name = fields.Char(
        string="Operation Type",
        required=True,
        translate=True,
    )
    active = fields.Boolean(
        string="Active",
        default=True,
    )
    sequence = fields.Integer(
        string="Sequence",
        help="Used to order the 'All Operations' kanban view",
    )
    sequence_id = fields.Many2one(
        comodel_name="ir.sequence",
        string="Reference Sequence",
        check_company=True,
        copy=False,
    )
    sequence_code = fields.Char(
        string="Sequence Prefix",
        required=True,
    )
    color = fields.Integer(string="Color")
    default_location_src_id = fields.Many2one(
        comodel_name="stock.location",
        string="Source Location",
        required=True,
        compute="_compute_default_location_src_id",
        store=True,
        precompute=True,
        readonly=False,
        check_company=True,
        help="This is the default source location when this operation is manually created. However, it is possible to change it afterwards or that the routes use another one by default.",
    )
    default_location_dest_id = fields.Many2one(
        comodel_name="stock.location",
        string="Destination Location",
        required=True,
        compute="_compute_default_location_dest_id",
        store=True,
        precompute=True,
        readonly=False,
        check_company=True,
        help="This is the default destination location when this operation is manually created. However, it is possible to change it afterwards or that the routes use another one by default.",
    )
    code = fields.Selection(
        selection=[
            ("incoming", "Receipt"),
            ("outgoing", "Delivery"),
            ("internal", "Internal Transfer"),
        ],
        string="Type of Operation",
        required=True,
        default="incoming",
    )
    return_picking_type_id = fields.Many2one(
        comodel_name="stock.picking.type",
        string="Operation Type for Returns",
        check_company=True,
        index="btree_not_null",
    )
    show_entire_packs = fields.Boolean(
        string="Move Entire Packages",
        default=False,
        help="If ticked, packages to move will be directly displayed in Barcode instead of the products they contain",
    )
    set_package_type = fields.Boolean(
        string="Set Package Type",
        default=False,
        help="If ticked, you will be able to select which package or package type to use in a put in pack",
    )
    warehouse_id = fields.Many2one(
        comodel_name="stock.warehouse",
        string="Warehouse",
        compute="_compute_warehouse_id",
        store=True,
        readonly=False,
        check_company=True,
        ondelete="cascade",
    )
    use_create_lots = fields.Boolean(
        string="Create New Lots/Serial Numbers",
        default=True,
        compute="_compute_use_create_lots",
        store=True,
        readonly=False,
        help="If this is checked only, it will suppose you want to create new Lots/Serial Numbers, so you can provide them in a text field. ",
    )
    use_existing_lots = fields.Boolean(
        string="Use Existing Lots/Serial Numbers",
        default=True,
        compute="_compute_use_existing_lots",
        store=True,
        readonly=False,
        help="If this is checked, you will be able to choose the Lots/Serial Numbers. You can also decide to not put lots in this operation type.  This means it will create stock with no lot or not put a restriction on the lot taken. ",
    )
    print_label = fields.Boolean(
        string="Generate Shipping Labels",
        compute="_compute_print_label",
        store=True,
        readonly=False,
        help="Check this box if you want to generate shipping label in this operation.",
    )
    show_operations = fields.Boolean(
        string="Show Detailed Operations",
        default=False,
        help="If this checkbox is ticked, the pickings lines will represent detailed stock operations. If not, the picking lines will represent an aggregate of detailed stock operations.",
    )
    reservation_method = fields.Selection(
        selection=[
            ("at_confirm", "At Confirmation"),
            ("manual", "Manually"),
            ("by_date", "Before scheduled date"),
        ],
        string="Reservation Method",
        required=True,
        default="at_confirm",
        help="How products in transfers of this operation type should be reserved.",
    )
    reservation_days_before = fields.Integer(
        string="Days",
        help="Maximum number of days before scheduled date that products should be reserved.",
    )
    reservation_days_before_priority = fields.Integer(
        string="Days when starred",
        help="Maximum number of days before scheduled date that priority picking products should be reserved.",
    )
    auto_show_reception_report = fields.Boolean(
        string="Show Reception Report at Validation",
        help="If this checkbox is ticked, Odoo will automatically show the reception report (if there are moves to allocate to) when validating.",
    )
    auto_print_delivery_slip = fields.Boolean(
        string="Auto Print Delivery Slip",
        help="If this checkbox is ticked, Odoo will automatically print the delivery slip of a picking when it is validated.",
    )
    auto_print_return_slip = fields.Boolean(
        string="Auto Print Return Slip",
        help="If this checkbox is ticked, Odoo will automatically print the return slip of a picking when it is validated.",
    )

    auto_print_product_labels = fields.Boolean(
        string="Auto Print Product Labels",
        help="If this checkbox is ticked, Odoo will automatically print the product labels of a picking when it is validated.",
    )
    product_label_format = fields.Selection(
        selection=[
            ("dymo", "Dymo"),
            ("2x7xprice", "2 x 7 with price"),
            ("4x7xprice", "4 x 7 with price"),
            ("4x12", "4 x 12"),
            ("4x12xprice", "4 x 12 with price"),
            ("zpl", "ZPL Labels"),
            ("zplxprice", "ZPL Labels with price"),
        ],
        string="Product Label Format to auto-print",
        default="2x7xprice",
    )
    auto_print_lot_labels = fields.Boolean(
        string="Auto Print Lot/SN Labels",
        help="If this checkbox is ticked, Odoo will automatically print the lot/SN labels of a picking when it is validated.",
    )
    lot_label_format = fields.Selection(
        selection=[
            ("4x12_lots", "4 x 12 - One per lot/SN"),
            ("4x12_units", "4 x 12 - One per unit"),
            ("zpl_lots", "ZPL Labels - One per lot/SN"),
            ("zpl_units", "ZPL Labels - One per unit"),
        ],
        string="Lot Label Format to auto-print",
        default="4x12_lots",
    )
    auto_print_reception_report = fields.Boolean(
        string="Auto Print Reception Report",
        help="If this checkbox is ticked, Odoo will automatically print the reception report of a picking when it is validated and has assigned moves.",
    )
    auto_print_reception_report_labels = fields.Boolean(
        string="Auto Print Reception Report Labels",
        help="If this checkbox is ticked, Odoo will automatically print the reception report labels of a picking when it is validated.",
    )
    auto_print_packages = fields.Boolean(
        string="Auto Print Packages",
        help="If this checkbox is ticked, Odoo will automatically print the packages and their contents of a picking when it is validated.",
    )

    auto_print_package_label = fields.Boolean(
        string="Auto Print Package Label",
        help='If this checkbox is ticked, Odoo will automatically print the package label when "Put in Pack" button is used.',
    )
    package_label_to_print = fields.Selection(
        selection=[("pdf", "PDF"), ("zpl", "ZPL")],
        string="Package Label to Print",
        default="pdf",
    )

    count_picking_draft = fields.Integer(compute="_compute_picking_count")
    count_picking_ready = fields.Integer(compute="_compute_picking_count")
    count_picking = fields.Integer(compute="_compute_picking_count")
    count_picking_waiting = fields.Integer(compute="_compute_picking_count")
    count_picking_late = fields.Integer(compute="_compute_picking_count")
    count_picking_backorders = fields.Integer(compute="_compute_picking_count")
    count_move_ready = fields.Integer(compute="_compute_move_count")
    hide_reservation_method = fields.Boolean(compute="_compute_hide_reservation_method")
    barcode = fields.Char(string="Barcode", copy=False)
    company_id = fields.Many2one(
        comodel_name="res.company",
        string="Company",
        required=True,
        default=lambda s: s.env.company.id,
        index=True,
    )
    create_backorder = fields.Selection(
        selection=[("ask", "Ask"), ("always", "Always"), ("never", "Never")],
        string="Create Backorder",
        required=True,
        default="ask",
        help="When validating a transfer:\n"
        " * Ask: users are asked to choose if they want to make a backorder for remaining products\n"
        " * Always: a backorder is automatically created for the remaining products\n"
        " * Never: remaining products are cancelled",
    )
    show_picking_type = fields.Boolean(compute="_compute_show_picking_type")

    picking_properties_definition = fields.PropertiesDefinition("Picking Properties")
    favorite_user_ids = fields.Many2many(
        comodel_name="res.users",
        relation="picking_type_favorite_user_rel",
        column1="picking_type_id",
        column2="user_id",
    )
    is_favorite = fields.Boolean(
        string="Show Operation in Overview",
        compute="_compute_is_favorite",
        compute_sudo=True,
        inverse="_inverse_is_favorite",
        search="_search_is_favorite",
    )
    kanban_dashboard_graph = fields.Text(compute="_compute_kanban_dashboard_graph")
    move_type = fields.Selection(
        selection=[
            ("direct", "As soon as possible"),
            ("one", "When all products are ready"),
        ],
        string="Shipping Policy",
        required=True,
        default="direct",
        help="It specifies goods to be transferred partially or all at once",
    )


    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if not vals.get("sequence_id") and vals.get("sequence_code"):
                company_id = vals.get("company_id") or self.env.company.id
                if vals.get("warehouse_id"):
                    wh = self.env["stock.warehouse"].browse(vals["warehouse_id"])
                    vals["sequence_id"] = (
                        self.env["ir.sequence"]
                        .sudo()
                        .create(
                            {
                                "name": _(
                                    "%(warehouse)s Sequence %(code)s",
                                    warehouse=wh.name,
                                    code=vals["sequence_code"],
                                ),
                                "prefix": wh.code + "/" + vals["sequence_code"] + "/",
                                "padding": 5,
                                "company_id": company_id,
                            }
                        )
                        .id
                    )
                else:
                    vals["sequence_id"] = (
                        self.env["ir.sequence"]
                        .sudo()
                        .create(
                            {
                                "name": _(
                                    "Sequence %(code)s", code=vals["sequence_code"]
                                ),
                                "prefix": vals["sequence_code"],
                                "padding": 5,
                                "company_id": company_id,
                            }
                        )
                        .id
                    )
        return super().create(vals_list)

    def write(self, vals):
        if "company_id" in vals:
            for picking_type in self:
                if picking_type.company_id.id != vals["company_id"]:
                    raise UserError(
                        _(
                            "Changing the company of this record is forbidden at this point, you should rather archive it and create a new one."
                        )
                    )
        types_changing_warehouse = self.browse()
        if vals.get("warehouse_id"):
            types_changing_warehouse = self.filtered(
                lambda picking_type: (
                    picking_type.warehouse_id.id != vals["warehouse_id"]
                ),
            )
        if "sequence_code" in vals:
            for picking_type in self:
                if picking_type.warehouse_id:
                    picking_type.sequence_id.sudo().write(
                        {
                            "name": _(
                                "%(warehouse)s Sequence %(code)s",
                                warehouse=picking_type.warehouse_id.name,
                                code=vals["sequence_code"],
                            ),
                            "prefix": picking_type.warehouse_id.code
                            + "/"
                            + vals["sequence_code"]
                            + "/",
                            "padding": 5,
                            "company_id": picking_type.company_id.id,
                        }
                    )
                else:
                    picking_type.sequence_id.sudo().write(
                        {
                            "name": _("Sequence %(code)s", code=vals["sequence_code"]),
                            "prefix": vals["sequence_code"],
                            "padding": 5,
                            "company_id": picking_type.company_id.id,
                        }
                    )
        days_changed = (
            "reservation_days_before" in vals
            or "reservation_days_before_priority" in vals
        )
        new_method = vals.get("reservation_method")
        if new_method and new_method != "by_date":
            if picking_types := self.filtered(
                lambda p: p.reservation_method == "by_date"
            ):
                moves = self.env["stock.move"].search(
                    [
                        ("picking_type_id", "in", picking_types.ids),
                        ("state", "not in", ("assigned", "done", "cancel")),
                    ]
                )
                moves.date_reservation = False
        elif new_method == "by_date" or days_changed:
            if new_method == "by_date" and not days_changed:
                picking_types = self.filtered(
                    lambda p: p.reservation_method != "by_date"
                )
            elif new_method == "by_date":
                picking_types = self
            else:
                picking_types = self.filtered(
                    lambda p: p.reservation_method == "by_date"
                )
            if picking_types:
                domain = [
                    ("picking_type_id", "in", picking_types.ids),
                    (
                        "state",
                        "in",
                        ("draft", "confirmed", "waiting", "partially_available"),
                    ),
                ]
                group_by = ["picking_type_id"]
                aggregates = ["id:recordset"]
                for picking_type, moves in self.env["stock.move"]._read_group(
                    domain, group_by, aggregates
                ):
                    common_days = vals.get(
                        "reservation_days_before",
                        picking_type.reservation_days_before,
                    )
                    priority_days = vals.get(
                        "reservation_days_before_priority",
                        picking_type.reservation_days_before_priority,
                    )
                    for move in moves:
                        move.date_reservation = fields.Date.to_date(
                            move.date
                        ) - timedelta(
                            days=(
                                priority_days if move.priority == "1" else common_days
                            )
                        )

        res = super().write(vals)

        if types_changing_warehouse:
            new_warehouse = self.env["stock.warehouse"].browse(vals["warehouse_id"])
            for picking_type in types_changing_warehouse:
                updates = {}
                if "default_location_src_id" not in vals:
                    src = picking_type.default_location_src_id
                    if picking_type.code != "incoming" and (
                        not src
                        or (src.warehouse_id and src.warehouse_id != new_warehouse)
                    ):
                        updates["default_location_src_id"] = (
                            new_warehouse.lot_stock_id.id
                        )
                if "default_location_dest_id" not in vals:
                    dest = picking_type.default_location_dest_id
                    if picking_type.code != "outgoing" and (
                        not dest
                        or (dest.warehouse_id and dest.warehouse_id != new_warehouse)
                    ):
                        updates["default_location_dest_id"] = (
                            new_warehouse.lot_stock_id.id
                        )
                if updates:
                    picking_type.write(updates)
        return res

    def copy_data(self, default=None):
        default = dict(default or {})
        vals_list = super().copy_data(default=default)
        for picking, vals in zip(self, vals_list, strict=True):
            if "name" not in default:
                vals["name"] = _("%s (copy)", picking.name)
            if "sequence_code" not in default and "sequence_id" not in default:
                vals["sequence_code"] = _("%s (copy)", picking.sequence_code)
        return vals_list

    def copy_translations(self, new, excluded=()):
        super().copy_translations(new, excluded=(*excluded, "name"))
        self._copy_translations_of_renamed_field(
            new, "name", lambda record, term: record.env._("%s (copy)", term)
        )

    def _order_field_to_sql(self, alias, field_name, direction, nulls, query):
        if field_name == "is_favorite":
            sql_field = SQL(
                "%s IN (SELECT picking_type_id FROM picking_type_favorite_user_rel WHERE user_id = %s)",
                SQL.identifier(alias, "id"),
                self.env.uid,
            )
            if query._any_value_orderby:
                sql_field = SQL("ANY_VALUE(%s)", sql_field)
            else:
                query._order_groupby.append(sql_field)
            return SQL("%s %s %s", sql_field, direction, nulls)

        return super()._order_field_to_sql(alias, field_name, direction, nulls, query)


    def _compute_is_favorite(self):
        for picking_type in self:
            picking_type.is_favorite = self.env.user in picking_type.favorite_user_ids

    @api.depends("code")
    def _compute_hide_reservation_method(self):
        for rec in self:
            rec.hide_reservation_method = rec.code == "incoming"

    def _compute_picking_count(self):
        late_cutoff = (
            self.env["stock.picking"]
            ._date_category_boundaries()["today"]
            .astimezone(UTC)
            .replace(tzinfo=None)
        )
        counts_by_type_state = {
            (picking_type.id, state): count
            for picking_type, state, count in self.env["stock.picking"]._read_group(
                [
                    ("state", "in", ("draft", "confirmed", "waiting", "assigned")),
                    ("picking_type_id", "in", self.ids),
                ],
                ["picking_type_id", "state"],
                ["__count"],
            )
        }

        def state_count(picking_type_id, states):
            return sum(
                counts_by_type_state.get((picking_type_id, state), 0)
                for state in states
            )

        extra_domains = {
            "count_picking_late": [
                ("state", "in", ("assigned", "waiting", "confirmed")),
                "|",
                ("date_planned", "<", late_cutoff),
                ("has_deadline_issue", "=", True),
            ],
            "count_picking_backorders": [
                ("backorder_id", "!=", False),
                ("state", "in", ("confirmed", "assigned", "waiting")),
            ],
        }
        for field_name, domain in extra_domains.items():
            data = self.env["stock.picking"]._read_group(
                domain + [("picking_type_id", "in", self.ids)],
                ["picking_type_id"],
                ["__count"],
            )
            count = {picking_type.id: count for picking_type, count in data}
            for record in self:
                record[field_name] = count.get(record.id, 0)
        for record in self:
            record.count_picking_draft = state_count(record.id, ("draft",))
            record.count_picking_waiting = state_count(
                record.id, ("confirmed", "waiting")
            )
            record.count_picking_ready = state_count(record.id, ("assigned",))
            record.count_picking = state_count(
                record.id, ("assigned", "waiting", "confirmed")
            )

    def _compute_move_count(self):
        data = self.env["stock.move"]._read_group(
            [("state", "=", "assigned"), ("picking_type_id", "in", self.ids)],
            ["picking_type_id"],
            ["__count"],
        )
        count = {picking_type.id: count for picking_type, count in data}
        for record in self:
            record["count_move_ready"] = count.get(record.id, 0)

    @api.depends("warehouse_id")
    def _compute_display_name(self):
        """Display 'Warehouse_name: PickingType_name'"""
        for picking_type in self:
            if picking_type.warehouse_id:
                picking_type.display_name = (
                    f"{picking_type.warehouse_id.name}: {picking_type.name}"
                )
            else:
                picking_type.display_name = picking_type.name

    @api.depends("code")
    def _compute_use_create_lots(self):
        for picking_type in self:
            if picking_type.code == "incoming":
                picking_type.use_create_lots = True

    @api.depends("code")
    def _compute_use_existing_lots(self):
        for picking_type in self:
            if picking_type.code == "outgoing":
                picking_type.use_existing_lots = True

    @api.depends("code")
    def _compute_default_location_src_id(self):
        # Resolved once for the batch, and only when a record actually needs it:
        # `_get_partner_location` may search, and most batches hold no incoming
        # type at all.
        supplier_location = (
            self.env["stock.warehouse"]._get_partner_location("supplier")
            if any(picking_type.code == "incoming" for picking_type in self)
            else self.env["stock.location"]
        )
        for picking_type in self:
            if picking_type.code == "incoming":
                picking_type.default_location_src_id = supplier_location.id
            else:
                if not picking_type.warehouse_id:
                    self.env["stock.warehouse"]._warehouse_redirect_warning()
                picking_type.default_location_src_id = (
                    picking_type.warehouse_id.lot_stock_id.id
                )

    @api.depends("code")
    def _compute_default_location_dest_id(self):
        customer_location = (
            self.env["stock.warehouse"]._get_partner_location("customer")
            if any(picking_type.code == "outgoing" for picking_type in self)
            else self.env["stock.location"]
        )
        for picking_type in self:
            if picking_type.code == "outgoing":
                picking_type.default_location_dest_id = customer_location.id
            else:
                if not picking_type.warehouse_id:
                    self.env["stock.warehouse"]._warehouse_redirect_warning()
                picking_type.default_location_dest_id = (
                    picking_type.warehouse_id.lot_stock_id.id
                )

    @api.depends("code")
    def _compute_print_label(self):
        for picking_type in self:
            if picking_type.code in ("incoming", "internal"):
                picking_type.print_label = False
            elif picking_type.code == "outgoing":
                picking_type.print_label = True

    @api.depends("company_id")
    def _compute_warehouse_id(self):
        for picking_type in self:
            if picking_type.warehouse_id:
                continue
            if picking_type.company_id:
                warehouse = self.env["stock.warehouse"].search(
                    [("company_id", "=", picking_type.company_id.id)], limit=1
                )
                picking_type.warehouse_id = warehouse

    @api.depends("code")
    def _compute_show_picking_type(self):
        for record in self:
            record.show_picking_type = record.code in [
                "incoming",
                "outgoing",
                "internal",
            ]

    def _compute_kanban_dashboard_graph(self):
        grouped_records = self._get_aggregated_records_by_date()

        summaries = {}
        for picking_type_id, data, data_series_name in grouped_records:
            summary = {
                "data_series_name": data_series_name,
                "total_before": 0,
                "total_yesterday": 0,
                "total_today": 0,
                "total_day_1": 0,
                "total_day_2": 0,
                "total_after": 0,
            }
            if isinstance(data, dict):
                for date_category, count in data.items():
                    summary["total_" + date_category] += count
            else:
                for p_date in data:
                    date_category = self.calculate_date_category(p_date)
                    if date_category:
                        summary["total_" + date_category] += 1
            summaries[picking_type_id] = summary

        self._prepare_graph_data(summaries)


    def _inverse_is_favorite(self):
        sudoed_self = self.sudo()
        to_fav = sudoed_self.filtered(
            lambda picking_type: self.env.user not in picking_type.favorite_user_ids
        )
        to_fav.write({"favorite_user_ids": [(4, self.env.uid)]})
        (sudoed_self - to_fav).write({"favorite_user_ids": [(3, self.env.uid)]})


    @api.model
    def _search_is_favorite(self, operator, value):
        if operator != "in":
            return NotImplemented
        return [("favorite_user_ids", "in", [self.env.uid])]

    @api.model
    def _search_display_name(self, operator, value):
        if operator == "in":
            return Domain.OR(self._search_display_name("=", v) for v in value)
        if operator == "not in":
            return NotImplemented
        parts = isinstance(value, str) and value.split(": ", 1)
        if parts and len(parts) == 2:
            return (
                Domain("warehouse_id.name", operator, parts[0])
                & Domain("name", operator, parts[1])
            ) | Domain("name", operator, value)
        if operator == "=":
            operator = "in"
            value = [value]
        return super()._search_display_name(operator, value)


    @api.onchange("code")
    def _onchange_picking_code(self):
        if self.code == "internal" and not self.env.user.has_group(
            "stock.group_stock_multi_locations"
        ):
            return {
                "warning": {
                    "message": _(
                        "You need to activate storage locations to be able to do internal operation types."
                    )
                }
            }
        return None

    @api.onchange("sequence_code")
    def _onchange_sequence_code(self):
        if not self.sequence_code:
            return None
        domain = [
            ("sequence_code", "=", self.sequence_code),
            "|",
            ("company_id", "=", self.company_id.id),
            ("company_id", "=", False),
        ]
        if self._origin.id:
            domain += [("id", "!=", self._origin.id)]
        picking_type = self.env["stock.picking.type"].search(domain, limit=1)
        if picking_type and picking_type.sequence_id != self.sequence_id:
            return {
                "warning": {
                    "message": _(
                        "This sequence prefix is already being used by another operation type. It is recommended that you select a unique prefix "
                        "to avoid issues and/or repeated reference values or assign the existing reference sequence to this operation type."
                    )
                }
            }
        return None


    @api.model
    def action_redirect_to_barcode_installation(self):
        action = self.env["ir.actions.act_window"]._for_xml_id("base.open_module_tree")
        action["context"] = dict(
            literal_eval(action["context"]), search_default_name="Barcode"
        )
        return action


    def _get_action(self, action_xmlid):
        action = self.env["ir.actions.actions"]._for_xml_id(action_xmlid)
        context = {}

        if self:
            action["display_name"] = self.display_name
            context.update(
                {
                    "default_picking_type_id": self.id,
                    "default_company_id": self.company_id.id,
                }
            )
        else:
            allowed_company_ids = self.env.context.get("allowed_company_ids", [])
            if allowed_company_ids:
                context.update(
                    {
                        "default_company_id": allowed_company_ids[0],
                    }
                )

        action_context = literal_eval(action["context"])
        context = {**action_context, **context}
        action["context"] = context
        if self:
            action["domain"] = [("picking_type_id", "=", self.id)]

        action["help"] = self.env["ir.ui.view"]._render_template(
            "stock.help_message_template",
            {
                "picking_type_code": context.get("restricted_picking_type_code")
                or self.code,
            },
        )

        return action

    def get_action_picking_tree_late(self):
        return self._get_action("stock.action_picking_tree_late")

    def get_action_picking_tree_backorder(self):
        return self._get_action("stock.action_picking_tree_backorder")

    def get_action_picking_tree_waiting(self):
        return self._get_action("stock.action_picking_tree_waiting")

    def get_action_picking_tree_ready(self):
        return self._get_action("stock.action_picking_tree_ready")

    def get_action_picking_type_moves_analysis(self):
        action = self.env["ir.actions.actions"]._for_xml_id("stock.stock_move_action")
        action["domain"] = Domain.AND(
            [action["domain"] or [], [("picking_type_id", "=", self.id)]]
        )
        return action

    def get_stock_picking_action_picking_type(self):
        if self.code == "incoming":
            return self._get_action("stock.action_picking_tree_incoming")
        if self.code == "outgoing":
            return self._get_action("stock.action_picking_tree_outgoing")
        if self.code == "internal":
            return self._get_action("stock.action_picking_tree_internal")
        return self._get_action("stock.stock_picking_action_picking_type")

    def get_action_picking_type_ready_moves(self):
        return self._get_action("stock.action_get_picking_type_ready_moves")

    def _get_aggregated_records_by_date(self):
        """
        Returns a list, each element containing 3 values:
        * picking type ID
        * per-date-category counts of that type's open (assigned/waiting/confirmed)
          pickings, as a ``{date_category: count}`` dict — overrides adding other
          source records (e.g. mrp, repair) may instead return the legacy list of
          raw datetime values, which `_compute_kanban_dashboard_graph` still
          classifies one by one
        * data series name, used to display it in the graph
        """
        if not self:
            return []
        counts_by_type = self._get_date_category_counts(
            "stock.picking",
            "date_planned",
            [("state", "in", ["assigned", "waiting", "confirmed"])],
        )
        label = self.env._("Transfers")
        return [
            (picking_type_id, counts, label)
            for picking_type_id, counts in counts_by_type.items()
        ]

    def _get_date_category_counts(self, model_name, date_field, domain):
        """Per-date-category counts of ``model_name``'s open records, keyed by
        picking type: ``{picking_type_id: {date_category: count}}``.

        Buckets in SQL — one grouped COUNT per (picking type, date category)
        using the same boundaries as `calculate_date_category` — instead of
        array_agg-ing every record's datetime out of PostgreSQL and classifying
        them one by one in Python on every dashboard render. Shared by the
        dashboard sources (stock pickings; mrp productions and repair orders in
        their overrides): ``model_name`` needs a ``picking_type_id`` field and
        a datetime ``date_field``.
        """
        model = self.env[model_name]
        model.browse().check_access("read")
        query = model._search(
            Domain(domain)
            & Domain("picking_type_id", "in", self.ids)
            & Domain(date_field, "!=", False),
        )
        counts_by_type = {picking_type_id: {} for picking_type_id in self.ids}
        if query.is_empty():
            return counts_by_type
        bounds = {
            key: value.astimezone(UTC).replace(tzinfo=None)
            for key, value in self.env[
                "stock.picking"
            ]._date_category_boundaries().items()
        }
        picking_type_sql = model._field_to_sql(model._table, "picking_type_id", query)
        date_sql = model._field_to_sql(model._table, date_field, query)
        category_sql = SQL(
            """CASE
                WHEN %(date_value)s < %(yesterday)s THEN 'before'
                WHEN %(date_value)s < %(today)s THEN 'yesterday'
                WHEN %(date_value)s < %(day_1)s THEN 'today'
                WHEN %(date_value)s < %(day_2)s THEN 'day_1'
                WHEN %(date_value)s < %(day_3)s THEN 'day_2'
                ELSE 'after'
            END""",
            date_value=date_sql,
            **bounds,
        )
        query.groupby = SQL("1, 2")
        rows = self.env.execute_query(
            query.select(picking_type_sql, category_sql, SQL("COUNT(*)"))
        )
        for picking_type_id, date_category, count in rows:
            counts_by_type[picking_type_id][date_category] = count
        return counts_by_type

    def _get_code_report_name(self):
        self.ensure_one()
        code_names = {
            "outgoing": _("Delivery Note"),
            "incoming": _("Goods Receipt Note"),
            "internal": _("Internal Move"),
        }
        return code_names.get(self.code)

    def _prepare_graph_data(self, summaries):
        """Convert each picking type summary into dashboard graph data.

        If all values in a graph are 0, it is assigned the "sample" type instead.
        """
        data_category_mapping = {
            "total_before": {"label": _("Before"), "type": "past"},
            "total_yesterday": {"label": _("Yesterday"), "type": "past"},
            "total_today": {"label": _("Today"), "type": "present"},
            "total_day_1": {"label": _("Tomorrow"), "type": "future"},
            "total_day_2": {"label": _("The day after tomorrow"), "type": "future"},
            "total_after": {"label": _("After"), "type": "future"},
        }

        for picking_type in self:
            picking_type_summary = summaries.get(picking_type.id)
            empty = all(picking_type_summary[k] == 0 for k in data_category_mapping)
            graph_data = [
                {
                    "key": (
                        _("Sample data")
                        if empty
                        else picking_type_summary["data_series_name"]
                    ),
                    "picking_type_id": None if empty else picking_type.id,
                    "values": [
                        dict(
                            v,
                            value=picking_type_summary[k],
                            type="sample" if empty else v["type"],
                            category=k.removeprefix("total_"),
                        )
                        for k, v in data_category_mapping.items()
                    ],
                }
            ]
            picking_type.kanban_dashboard_graph = json.dumps(graph_data)
