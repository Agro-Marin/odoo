from odoo import Command, api, fields, models
from odoo.libs.debug_log import DebugLog
from odoo.tools import TransactionMemo

ROUTE_RULE_ACTIONS = TransactionMemo(
    "stock.route.rule_actions", invalidated_by=("stock.rule",)
)
_debug = DebugLog(__name__)


class StockRoute(models.Model):
    _name = "stock.route"
    _description = "Inventory Routes"
    _inherit = ["mixin.mail.thread"]
    _order = "sequence"
    _check_company_auto = True

    name = fields.Char(
        string="Route",
        translate=True,
        required=True,
        tracking=True,
    )
    active = fields.Boolean(
        default=True,
        tracking=True,
        help="If the active field is set to False, it will allow you to hide the route without removing it.",
    )
    sequence = fields.Integer(default=0)
    rule_ids = fields.One2many(
        comodel_name="stock.rule",
        inverse_name="route_id",
        string="Rules",
        copy=True,
    )
    product_selectable = fields.Boolean(
        string="Applicable on Product",
        default=True,
        tracking=True,
        help="When checked, the route will be selectable in the Inventory tab of the Product form.",
    )
    product_categ_selectable = fields.Boolean(
        string="Applicable on Product Category",
        tracking=True,
        help="When checked, the route will be selectable on the Product Category.",
    )
    warehouse_selectable = fields.Boolean(
        string="Applicable on Warehouse",
        tracking=True,
        help="When a warehouse is selected for this route, this route should be seen as the default route when products pass through this warehouse.",
    )
    package_type_selectable = fields.Boolean(
        string="Applicable on Package Type",
        tracking=True,
        help="When checked, the route will be selectable on package types",
    )
    supplied_wh_id = fields.Many2one(
        comodel_name="stock.warehouse",
        string="Supplied Warehouse",
        index="btree_not_null",
        tracking=True,
    )
    supplier_wh_id = fields.Many2one(
        comodel_name="stock.warehouse",
        string="Supplying Warehouse",
        tracking=True,
    )
    company_id = fields.Many2one(
        comodel_name="res.company",
        default=lambda self: self.env.company,
        index=True,
        tracking=True,
        help="Leave this field empty if this route is shared between all companies",
    )
    product_ids = fields.Many2many(
        comodel_name="product.template",
        relation="stock_route_product",
        column1="route_id",
        column2="product_id",
        string="Products",
        copy=False,
        check_company=True,
    )
    categ_ids = fields.Many2many(
        comodel_name="product.category",
        relation="stock_route_categ",
        column1="route_id",
        column2="categ_id",
        string="Product Categories",
        copy=False,
    )
    warehouse_domain_ids = fields.One2many(
        comodel_name="stock.warehouse",
        compute="_compute_warehouse_domain_ids",
    )
    warehouse_ids = fields.Many2many(
        comodel_name="stock.warehouse",
        relation="stock_route_warehouse",
        column1="route_id",
        column2="warehouse_id",
        string="Warehouses",
        copy=False,
        domain="[('id', 'in', warehouse_domain_ids)]",
        tracking=True,
    )

    def _has_rule_with_action(self, action):
        memo = ROUTE_RULE_ACTIONS(self.env)
        missing = [route_id for route_id in self.ids if route_id not in memo]
        if missing:
            memo.update(dict.fromkeys(missing, frozenset()))
            for route, actions in (
                self.env["stock.rule"]
                .sudo()
                ._read_group(
                    [("route_id", "in", missing)], ["route_id"], ["action:array_agg"]
                )
            ):
                memo[route.id] = frozenset(actions)
        return any(action in memo[route_id] for route_id in self.ids)

    @api.constrains("company_id", "rule_ids")
    def _check_company_consistency(self):
        self.filtered("company_id").rule_ids._check_company_consistency()

    @_debug.perf.timed
    def write(self, vals):
        if _debug.lifecycle.enabled:
            _debug.lifecycle("write", routes=self, keys=sorted(vals))
        if "active" in vals:
            toggled = self.filtered(lambda route: route.active != bool(vals["active"]))
            all_rules = toggled.with_context(active_test=False).rule_ids.sudo()
            _debug.lifecycle(
                "write_active_cascade", active=vals["active"], rules=all_rules
            )
            if vals["active"]:
                all_rules.filtered(
                    lambda rule: rule.location_dest_id.active
                ).action_unarchive()
            else:
                all_rules.action_archive()
        res = super().write(vals)
        if vals.get("active"):
            for warehouse in self.sudo().supplier_wh_id:
                warehouse._update_resupply_rule_activity()
        return res

    def copy_data(self, default=None):
        default = dict(default or {})
        vals_list = super().copy_data(default=default)
        if "name" not in default:
            for route, vals in zip(self, vals_list, strict=True):
                vals["name"] = self.env._("%s (copy)", route.name)
        return vals_list

    def copy_translations(self, new, excluded=()):
        super().copy_translations(new, excluded=(*excluded, "name"))
        self._copy_translations_of_renamed_field(
            new, "name", lambda record, term: record.env._("%s (copy)", term)
        )

    @api.depends("company_id")
    def _compute_warehouse_domain_ids(self):
        Warehouse = self.env["stock.warehouse"]
        per_company = {
            company.id: Warehouse.search([("company_id", "=", company.id)])
            for company in self.company_id
        }
        if not all(route.company_id for route in self):
            per_company[False] = Warehouse.search([])
        for route in self:
            route.warehouse_domain_ids = per_company[route.company_id.id]

    @api.onchange("company_id")
    def _onchange_company_id(self):
        if self.company_id:
            self.warehouse_ids = self.warehouse_ids.filtered(
                lambda w: w.company_id == self.company_id
            )

    @api.onchange("warehouse_selectable")
    def _onchange_warehouse_selectable(self):
        if not self.warehouse_selectable:
            self.warehouse_ids = [Command.clear()]

    def _is_valid_resupply_route_for_product(self, product):
        return False
