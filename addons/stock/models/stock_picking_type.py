import json
from datetime import UTC

from odoo import Command, _, api, fields, models
from odoo.exceptions import UserError
from odoo.fields import Domain
from odoo.tools import SQL

from odoo.addons.base.models.ir_actions import safe_eval_dict


class StockPickingType(models.Model):
    _name = "stock.picking.type"
    _inherit = ["mixin.date.category"]
    _description = "Picking Type"
    _order = "is_favorite desc, sequence, id"
    _rec_names_search = ["name", "warehouse_id.name"]
    _check_company_auto = True

    name = fields.Char(
        string="Operation Type",
        required=True,
        translate=True,
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
    active = fields.Boolean(
        string="Active",
        default=True,
    )
    sequence = fields.Integer(
        string="Sequence",
        help="Used to order the 'All Operations' kanban view",
    )
    color = fields.Integer(string="Color")
    barcode = fields.Char(string="Barcode", copy=False)

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

    company_id = fields.Many2one(
        comodel_name="res.company",
        string="Company",
        required=True,
        default=lambda s: s.env.company.id,
        index=True,
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

    return_picking_type_id = fields.Many2one(
        comodel_name="stock.picking.type",
        string="Operation Type for Returns",
        check_company=True,
        index="btree_not_null",
    )
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

    print_label = fields.Boolean(
        string="Generate Shipping Labels",
        compute="_compute_print_label",
        store=True,
        readonly=False,
        help="Check this box if you want to generate shipping label in this operation.",
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

    auto_show_reception_report = fields.Boolean(
        string="Show Reception Report at Validation",
        help="If this checkbox is ticked, Odoo will automatically show the reception report (if there are moves to allocate to) when validating.",
    )
    auto_print_reception_report = fields.Boolean(
        string="Auto Print Reception Report",
        help="If this checkbox is ticked, Odoo will automatically print the reception report of a picking when it is validated and has assigned moves.",
    )
    auto_print_reception_report_labels = fields.Boolean(
        string="Auto Print Reception Report Labels",
        help="If this checkbox is ticked, Odoo will automatically print the reception report labels of a picking when it is validated.",
    )

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

    show_operations = fields.Boolean(
        string="Show Detailed Operations",
        default=False,
        help="If this checkbox is ticked, the pickings lines will represent detailed stock operations. If not, the picking lines will represent an aggregate of detailed stock operations.",
    )
    hide_reservation_method = fields.Boolean(compute="_compute_hide_reservation_method")
    show_picking_type = fields.Boolean(compute="_compute_show_picking_type")

    count_picking_ready = fields.Integer(compute="_compute_picking_count")
    count_picking_waiting = fields.Integer(compute="_compute_picking_count")
    count_picking_late = fields.Integer(compute="_compute_picking_count")
    count_picking_backorders = fields.Integer(compute="_compute_picking_count")
    count_move_ready = fields.Integer(compute="_compute_move_count")
    kanban_dashboard_graph = fields.Text(compute="_compute_kanban_dashboard_graph")

    _sequence_code_uniq = models.UniqueIndex(
        "(company_id, warehouse_id, sequence_code) NULLS NOT DISTINCT",
        "Two operation types of the same warehouse cannot share a sequence "
        "prefix: they would issue the same reference numbers.",
    )
    _barcode_uniq = models.UniqueIndex(
        "(company_id, barcode) WHERE barcode IS NOT NULL",
        "Two operation types of the same company cannot share a barcode: a scan "
        "would have to guess which one it opens.",
    )
    _sequence_code_not_blank = models.Constraint(
        "CHECK (btrim(sequence_code) <> '')",
        "An operation type needs a sequence prefix: without one it gets no "
        "reference sequence, and its transfers cannot be numbered.",
    )

    @api.model_create_multi
    def create(self, vals_list):
        picking_types = super().create(vals_list)
        picking_types._update_reference_sequences()
        return picking_types

    def unlink(self):
        sequences = self.sequence_id
        result = super().unlink()
        self._unlink_orphaned_sequences(sequences)
        return result

    def write(self, vals):
        self._check_company_change(vals)
        types_changing_warehouse = (
            self.filtered(
                lambda picking_type: (
                    picking_type.warehouse_id.id != vals["warehouse_id"]
                ),
            )
            if vals.get("warehouse_id")
            else self.browse()
        )
        self._update_move_reservation_dates(vals)
        warehouse_before = {
            picking_type.id: picking_type.warehouse_id.id for picking_type in self
        }

        res = super().write(vals)

        moved = self.filtered(
            lambda picking_type: (
                picking_type.warehouse_id.id != warehouse_before[picking_type.id]
            )
        )
        if "sequence_code" in vals:
            self._update_reference_sequences()
        elif moved:
            moved._update_reference_sequences()
        if types_changing_warehouse:
            types_changing_warehouse._update_default_locations_for_warehouse(vals)
        return res

    def copy_data(self, default=None):
        default = dict(default or {})
        vals_list = super().copy_data(default=default)
        for picking, vals in zip(self, vals_list, strict=True):
            if "name" not in default:
                vals["name"] = _("%s (copy)", picking.name)
            if "sequence_code" not in default:
                vals["sequence_code"] = picking._get_unique_sequence_code()
        return vals_list

    def copy_translations(self, new, excluded=()):
        super().copy_translations(new, excluded=(*excluded, "name"))
        self._copy_translations_of_renamed_field(
            new, "name", lambda record, term: record.env._("%s (copy)", term)
        )

    def _check_company_change(self, vals):
        if "company_id" not in vals:
            return
        if self.filtered(lambda pt: pt.company_id.id != vals["company_id"]):
            raise UserError(
                _(
                    "Changing the company of this record is forbidden at this point, you should rather archive it and create a new one."
                )
            )

    def _update_move_reservation_dates(self, vals):
        days_changed = (
            "reservation_days_before" in vals
            or "reservation_days_before_priority" in vals
        )
        new_method = vals.get("reservation_method")
        if new_method and new_method != "by_date":
            leaving_by_date = self.filtered(
                lambda pt: pt.reservation_method == "by_date"
            )
            if leaving_by_date:
                self.env["stock.move"].search(
                    [
                        ("picking_type_id", "in", leaving_by_date.ids),
                        ("state", "not in", ("assigned", "done", "cancel")),
                    ]
                ).date_reservation = False
            return
        if not (new_method == "by_date" or days_changed):
            return

        if new_method == "by_date" and not days_changed:
            picking_types = self.filtered(lambda pt: pt.reservation_method != "by_date")
        elif new_method == "by_date":
            picking_types = self
        else:
            picking_types = self.filtered(lambda pt: pt.reservation_method == "by_date")
        if not picking_types:
            return

        for picking_type, moves in self.env["stock.move"]._read_group(
            [
                ("picking_type_id", "in", picking_types.ids),
                (
                    "state",
                    "in",
                    ("draft", "confirmed", "waiting", "partially_available"),
                ),
            ],
            ["picking_type_id"],
            ["id:recordset"],
        ):
            common_days = vals.get(
                "reservation_days_before", picking_type.reservation_days_before
            )
            priority_days = vals.get(
                "reservation_days_before_priority",
                picking_type.reservation_days_before_priority,
            )
            moves._set_reservation_date_from_days(common_days, priority_days)

    def _update_default_locations_for_warehouse(self, vals):
        new_warehouse = self.warehouse_id
        stock_location = new_warehouse.lot_stock_id
        to_update = {}
        for picking_type in self:
            if (
                "default_location_src_id" not in vals
                and picking_type.code != "incoming"
            ):
                source = picking_type.default_location_src_id
                if not source or (
                    source.warehouse_id and source.warehouse_id != new_warehouse
                ):
                    to_update.setdefault("default_location_src_id", self.browse())
                    to_update["default_location_src_id"] |= picking_type
            if (
                "default_location_dest_id" not in vals
                and picking_type.code != "outgoing"
            ):
                destination = picking_type.default_location_dest_id
                if not destination or (
                    destination.warehouse_id
                    and destination.warehouse_id != new_warehouse
                ):
                    to_update.setdefault("default_location_dest_id", self.browse())
                    to_update["default_location_dest_id"] |= picking_type
        for field_name, picking_types in to_update.items():
            picking_types.write({field_name: stock_location.id})

    def _order_field_to_sql(self, alias, field_name, direction, nulls, query):
        if field_name == "is_favorite":
            favorites = self._fields["favorite_user_ids"]
            sql_field = SQL(
                "%s IN (SELECT %s FROM %s WHERE %s = %s)",
                SQL.identifier(alias, "id"),
                SQL.identifier(favorites.column1),
                SQL.identifier(favorites.relation),
                SQL.identifier(favorites.column2),
                self.env.uid,
            )
            if query._any_value_orderby:
                sql_field = SQL("ANY_VALUE(%s)", sql_field)
            else:
                query._order_groupby.append(sql_field)
            return SQL("%s %s %s", sql_field, direction, nulls)

        return super()._order_field_to_sql(alias, field_name, direction, nulls, query)

    @api.depends("favorite_user_ids")
    @api.depends_context("uid")
    def _compute_is_favorite(self):
        for picking_type in self:
            picking_type.is_favorite = self.env.user in picking_type.favorite_user_ids

    @api.depends("code")
    def _compute_hide_reservation_method(self):
        for picking_type in self:
            picking_type.hide_reservation_method = picking_type.code == "incoming"

    @api.model
    def _transfer_codes(self):
        return {"incoming", "outgoing", "internal"}

    @api.depends("code")
    def _compute_show_picking_type(self):
        transfer_codes = self._transfer_codes()
        for picking_type in self:
            picking_type.show_picking_type = picking_type.code in transfer_codes

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
    def _compute_print_label(self):
        for picking_type in self:
            if picking_type.code in ("incoming", "internal"):
                picking_type.print_label = False
            elif picking_type.code == "outgoing":
                picking_type.print_label = True

    def _update_derived_default_location(self, field_name, derive):
        undecidable = self.browse()
        for picking_type in self:
            location = derive(picking_type)
            if location:
                picking_type[field_name] = location.id
            elif not picking_type[field_name]:
                undecidable |= picking_type
        if undecidable:
            undecidable._raise_undecidable_default_locations()

    def _raise_undecidable_default_locations(self):
        companies = self.company_id or self.env.company
        if not self.env["stock.warehouse"].search_count(
            [("company_id", "in", companies.ids)], limit=1
        ):
            self.env["stock.warehouse"]._warehouse_redirect_warning()
        raise UserError(
            _(
                "Operation type %(name)s has no warehouse, so its default "
                "locations cannot be derived. Set a warehouse on it, or give it "
                "explicit source and destination locations.",
                name=self[0].display_name or _("(new)"),
            )
        )

    @api.depends("code")
    def _compute_default_location_src_id(self):
        supplier_location = (
            self.env["stock.warehouse"]._get_partner_location("supplier")
            if any(picking_type.code == "incoming" for picking_type in self)
            else self.env["stock.location"]
        )
        self._update_derived_default_location(
            "default_location_src_id",
            lambda picking_type: (
                supplier_location
                if picking_type.code == "incoming"
                else picking_type.warehouse_id.lot_stock_id
            ),
        )

    @api.depends("code")
    def _compute_default_location_dest_id(self):
        customer_location = (
            self.env["stock.warehouse"]._get_partner_location("customer")
            if any(picking_type.code == "outgoing" for picking_type in self)
            else self.env["stock.location"]
        )
        self._update_derived_default_location(
            "default_location_dest_id",
            lambda picking_type: (
                customer_location
                if picking_type.code == "outgoing"
                else picking_type.warehouse_id.lot_stock_id
            ),
        )

    @api.depends("company_id")
    def _compute_warehouse_id(self):
        needing_warehouse = self.filtered(
            lambda picking_type: (
                not picking_type.warehouse_id and picking_type.company_id
            )
        )
        if not needing_warehouse:
            return
        first_by_company = {
            company.id: warehouse_id
            for company, warehouse_id in self.env["stock.warehouse"]._read_group(
                [("company_id", "in", needing_warehouse.company_id.ids)],
                ["company_id"],
                ["id:min"],
            )
        }
        for picking_type in needing_warehouse:
            picking_type.warehouse_id = first_by_company.get(
                picking_type.company_id.id, False
            )

    @api.depends("warehouse_id", "warehouse_id.name")
    def _compute_display_name(self):
        for picking_type in self:
            if picking_type.warehouse_id:
                picking_type.display_name = (
                    f"{picking_type.warehouse_id.name}: {picking_type.name}"
                )
            else:
                picking_type.display_name = picking_type.name

    _OPEN_PICKING_STATES = ("assigned", "waiting", "confirmed")

    def _picking_count_buckets(self, query):
        picking = self.env["stock.picking"]
        table = picking._table
        state = picking._field_to_sql(table, "state", query)
        is_open = SQL("%s IN %s", state, self._OPEN_PICKING_STATES)
        late_cutoff = (
            self._date_category_boundaries()["today"]
            .astimezone(UTC)
            .replace(tzinfo=None)
        )
        return {
            "count_picking_ready": SQL("%s = 'assigned'", state),
            "count_picking_waiting": SQL("%s IN ('confirmed', 'waiting')", state),
            "count_picking_late": SQL(
                "%s AND (%s < %s OR %s)",
                is_open,
                picking._field_to_sql(table, "date_planned", query),
                late_cutoff,
                picking._field_to_sql(table, "has_deadline_issue", query),
            ),
            "count_picking_backorders": SQL(
                "%s AND %s IS NOT NULL",
                is_open,
                picking._field_to_sql(table, "backorder_id", query),
            ),
        }

    def _compute_picking_count(self):
        picking = self.env["stock.picking"]
        query = picking._search(
            Domain("picking_type_id", "in", self.ids)
            & Domain("state", "in", self._OPEN_PICKING_STATES)
        )
        buckets = self._picking_count_buckets(query)
        counts = {}
        if not query.is_empty():
            group = picking._field_to_sql(picking._table, "picking_type_id", query)
            query.groupby = SQL("1")
            rows = self.env.execute_query(
                query.select(
                    group,
                    *(
                        SQL("COUNT(*) FILTER (WHERE %s)", condition)
                        for condition in buckets.values()
                    ),
                )
            )
            counts = {row[0]: row[1:] for row in rows}
        empty = (0,) * len(buckets)
        for record in self:
            for field_name, count in zip(
                buckets, counts.get(record.id, empty), strict=True
            ):
                record[field_name] = count

    def _compute_move_count(self):
        data = self.env["stock.move"]._read_group(
            [("state", "=", "assigned"), ("picking_type_id", "in", self.ids)],
            ["picking_type_id"],
            ["__count"],
        )
        count = {picking_type.id: count for picking_type, count in data}
        for record in self:
            record.count_move_ready = count.get(record.id, 0)

    def _compute_kanban_dashboard_graph(self):
        summaries = {}
        for (
            picking_type_id,
            counts,
            data_series_name,
        ) in self._get_aggregated_records_by_date():
            summary = summaries.setdefault(
                picking_type_id, self._get_empty_graph_summary(data_series_name)
            )
            for date_category, count in counts.items():
                summary["total_" + date_category] += count
        self._update_graph_data(summaries)

    @api.model
    def _search_is_favorite(self, operator, value):
        if operator != "in" or set(value) != {True}:
            return NotImplemented
        return [("favorite_user_ids", "in", [self.env.uid])]

    @api.model
    def _search_display_name(self, operator, value):
        if operator in ("in", "not in"):
            return NotImplemented
        warehouse_name, _sep, picking_type_name = (
            value.partition(": ") if isinstance(value, str) else ("", "", "")
        )
        if not (warehouse_name and picking_type_name):
            return super()._search_display_name(operator, value)
        positive = Domain.NEGATIVE_OPERATORS.get(operator, operator)
        matched = (
            Domain("warehouse_id.name", positive, warehouse_name)
            & Domain("name", positive, picking_type_name)
        ) | Domain("name", positive, value)
        return matched if positive == operator else ~matched

    def _inverse_is_favorite(self):
        to_favorite = self.filtered("is_favorite").sudo()
        to_favorite.favorite_user_ids = [Command.link(self.env.uid)]
        (self.sudo() - to_favorite).favorite_user_ids = [Command.unlink(self.env.uid)]

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

    @api.onchange("sequence_code", "warehouse_id")
    def _onchange_sequence_code(self):
        if not self.sequence_code:
            return None
        clashing = self._get_clashing_picking_type()
        if clashing and clashing.sequence_id != self.sequence_id:
            return {
                "warning": {
                    "message": _(
                        "This sequence prefix is already used by %(name)s%(archived)s. "
                        "Pick a unique prefix.",
                        name=clashing.display_name,
                        archived="" if clashing.active else _(" (archived)"),
                    )
                }
            }
        return None

    @api.model
    def action_redirect_to_barcode_installation(self):
        action = self.env["ir.actions.act_window"]._get_action_dict_by_xml_id("base.open_module_tree")
        action["context"] = dict(
            safe_eval_dict(action["context"], dict(self.env.context), {}),
            search_default_name="Barcode",
        )
        return action

    def action_view_pickings_late(self):
        return self._get_action("stock.action_picking_tree_late")

    def action_view_pickings_backorder(self):
        return self._get_action("stock.action_picking_tree_backorder")

    def action_view_pickings_waiting(self):
        return self._get_action("stock.action_picking_tree_waiting")

    def action_view_pickings_ready(self):
        return self._get_action("stock.action_picking_tree_ready")

    def action_view_moves_ready(self):
        return self._get_action("stock.action_get_picking_type_ready_moves")

    def action_view_moves_analysis(self):
        action = self.env["ir.actions.actions"]._get_action_dict_by_xml_id("stock.stock_move_action")
        domains = [action["domain"] or []]
        if self:
            self.ensure_one()
            domains.append([("picking_type_id", "=", self.id)])
        action["domain"] = Domain.AND(domains)
        return action

    def action_view_pickings(self):
        self._check_single_or_empty()
        action_by_code = {
            "incoming": "stock.action_picking_tree_incoming",
            "outgoing": "stock.action_picking_tree_outgoing",
            "internal": "stock.action_picking_tree_internal",
        }
        return self._get_action(
            action_by_code.get(self.code, "stock.stock_picking_action_picking_type")
        )

    def _get_aggregated_records_by_date(self):
        if not self:
            return []
        counts_by_type = self._get_date_category_counts(
            "stock.picking",
            "date_planned",
            "picking_type_id",
            [("state", "in", ["assigned", "waiting", "confirmed"])],
        )
        label = self.env._("Transfers")
        return [
            (picking_type_id, counts, label)
            for picking_type_id, counts in counts_by_type.items()
        ]

    @api.model
    def _get_empty_graph_summary(self, data_series_name):
        return {
            "data_series_name": data_series_name,
            **{f"total_{key}": 0 for key, *_ in self.DATE_CATEGORIES},
        }

    def _update_graph_data(self, summaries):
        data_category_mapping = {}
        for key, _upper, label, kind in self.DATE_CATEGORIES:
            text = self.env._(label)  # pylint: disable=gettext-variable
            data_category_mapping[f"total_{key}"] = {"label": text, "type": kind}

        for picking_type in self:
            summary = summaries.get(picking_type.id) or self._get_empty_graph_summary(
                self.env._("Transfers")
            )
            empty = all(summary[key] == 0 for key in data_category_mapping)
            graph_data = [
                {
                    "key": _("Sample data") if empty else summary["data_series_name"],
                    "picking_type_id": None if empty else picking_type.id,
                    "values": [
                        dict(
                            value,
                            value=summary[key],
                            type="sample" if empty else value["type"],
                            category=key.removeprefix("total_"),
                        )
                        for key, value in data_category_mapping.items()
                    ],
                }
            ]
            picking_type.kanban_dashboard_graph = json.dumps(graph_data)

    @api.constrains(
        "warehouse_id", "default_location_src_id", "default_location_dest_id"
    )
    def _check_default_locations_are_derivable(self):
        undecidable = self.filtered(
            lambda picking_type: (
                not picking_type.warehouse_id
                and not (
                    picking_type.default_location_src_id
                    and picking_type.default_location_dest_id
                )
            )
        )
        if undecidable:
            undecidable._raise_undecidable_default_locations()

    def _prepare_sequence_vals(self, warehouse_name=None, warehouse_code=None):
        self.ensure_one()
        warehouse = self.warehouse_id
        if not warehouse:
            return {
                "name": _("Sequence %(code)s", code=self.sequence_code),
                "prefix": self.sequence_code,
                "padding": 5,
                "company_id": self.company_id.id,
            }
        name = warehouse_name or warehouse.name
        code = warehouse._normalize_code(warehouse_code or warehouse.code)
        return {
            "name": _(
                "%(warehouse)s Sequence %(code)s",
                warehouse=name,
                code=self.sequence_code,
            ),
            "prefix": "%s/%s/" % (code, self.sequence_code),
            "padding": 5,
            "company_id": self.company_id.id,
        }

    def _update_reference_sequences(self, only=None):
        missing = self.browse()
        for picking_type in self:
            if not picking_type.sequence_code:
                continue
            if not picking_type.sequence_id:
                missing |= picking_type
                continue
            wanted = picking_type._prepare_sequence_vals()
            if only is not None:
                wanted = {name: value for name, value in wanted.items() if name in only}
            sequence = picking_type.sequence_id.sudo()
            changed = {
                name: value
                for name, value in wanted.items()
                if sequence._fields[name].convert_to_write(sequence[name], sequence)
                != value
            }
            if changed:
                sequence.write(changed)
        if missing:
            sequences = (
                self.env["ir.sequence"]
                .sudo()
                .create(
                    [picking_type._prepare_sequence_vals() for picking_type in missing]
                )
            )
            for picking_type, sequence in zip(missing, sequences, strict=True):
                picking_type.sequence_id = sequence.id

    @api.model
    def _unlink_orphaned_sequences(self, sequences):
        if not sequences:
            return
        still_referenced = (
            self.with_context(active_test=False)
            .search([("sequence_id", "in", sequences.ids)])
            .sequence_id
        )
        (sequences - still_referenced).sudo().unlink()

    def _sequence_scope_domain(self):
        self.ensure_one()
        return Domain("company_id", "=", self.company_id.id) & Domain(
            "warehouse_id", "=", self.warehouse_id.id or False
        )

    def _get_clashing_picking_type(self):
        self.ensure_one()
        domain = self._sequence_scope_domain() & Domain(
            "sequence_code", "=", self.sequence_code
        )
        if self._origin.id:
            domain &= Domain("id", "!=", self._origin.id)
        return (
            self.env["stock.picking.type"]
            .with_context(active_test=False)
            .search(domain, limit=1)
        )

    def _get_unique_sequence_code(self):
        self.ensure_one()
        pattern = (
            self.sequence_code.replace("\\", "\\\\")
            .replace("_", "\\_")
            .replace("%", "\\%")
        )
        taken = set(
            self.env["stock.picking.type"]
            .with_context(active_test=False)
            .search(
                self._sequence_scope_domain()
                & Domain("sequence_code", "=like", f"{pattern}%")
            )
            .mapped("sequence_code")
        )
        for index in range(2, len(taken) + 3):
            candidate = f"{self.sequence_code}{index}"
            if candidate not in taken:
                return candidate
        return self.sequence_code

    def _check_single_or_empty(self):
        if len(self) > 1:
            raise ValueError(
                f"an operation type action opens one type at a time, got {self!r}"
            )

    def _get_action(self, action_xmlid):
        self._check_single_or_empty()
        action = self.env["ir.actions.actions"]._get_action_dict_by_xml_id(action_xmlid)
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

        action_context = safe_eval_dict(action["context"], dict(self.env.context), {})
        context = {**action_context, **context}
        action["context"] = context
        if self:
            action["domain"] = [("picking_type_id", "=", self.id)]

        if action.get("res_model") == "stock.picking":
            action["help"] = self.env["ir.ui.view"]._render_template(
                "stock.help_message_template",
                {
                    "picking_type_code": context.get("restricted_picking_type_code")
                    or self.code,
                },
            )

        return action

    def _get_code_report_name(self):
        self.ensure_one()
        code_names = {
            "outgoing": _("Delivery Note"),
            "incoming": _("Goods Receipt Note"),
            "internal": _("Internal Move"),
        }
        return code_names.get(self.code)
