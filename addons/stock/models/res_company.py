from collections import defaultdict

from odoo import _, api, fields, models, modules
from odoo.exceptions import ValidationError


class ResCompany(models.Model):
    _inherit = "res.company"
    _check_company_auto = True

    # ------------------------------------------------------------
    # FIELDS
    # ------------------------------------------------------------

    internal_transit_location_id = fields.Many2one(
        comodel_name="stock.location",
        string="Internal Transit Location",
        check_company=True,
        ondelete="restrict",
        help="Used for resupply routes between warehouses that belong to this company",
    )
    stock_move_email_validation = fields.Boolean(
        string="Email Confirmation picking",
    )
    stock_mail_confirmation_template_id = fields.Many2one(
        comodel_name="mail.template",
        string="Email Template confirmation picking",
        default=lambda self: self._default_confirmation_mail_template(),
        domain="[('model', '=', 'stock.picking')]",
        help="Email sent to the customer once the order is done.",
    )
    annual_inventory_month = fields.Selection(
        selection=[
            ("1", "January"),
            ("2", "February"),
            ("3", "March"),
            ("4", "April"),
            ("5", "May"),
            ("6", "June"),
            ("7", "July"),
            ("8", "August"),
            ("9", "September"),
            ("10", "October"),
            ("11", "November"),
            ("12", "December"),
        ],
        string="Annual Inventory Month",
        default="12",
        help="Annual inventory month for products not in a location with a cyclic inventory date. Set to no month if no automatic annual inventory.",
    )
    annual_inventory_day = fields.Integer(
        string="Day of the month",
        default=31,
        help="""Day of the month when the annual inventory should occur. If zero or negative, then the first day of the month will be selected instead.
        If greater than the last day of a month, then the last day of the month will be selected instead.""",
    )
    horizon_days = fields.Integer(
        string="Replenishment Horizon",
        required=True,
        default=365,
        help="""Configure your horizon to trigger reordering rules earlier to get
         a head start on replenishment and avoid delays, or trigger it just-in-time
         ('0 days') to avoid overstocking.""",
    )

    # Text confirmation sent to the customer when a delivery is done. Channel is
    # pluggable: base ships 'sms' (stock_sms); stock_enterprise adds 'whatsapp'
    # via selection_add (whatsapp_stock).
    stock_text_confirmation = fields.Boolean(string="Stock Text Confirmation")
    stock_confirmation_type = fields.Selection(
        selection=[("sms", "SMS")],
        string="Confirmation Channel",
        default="sms",
        help="Channel used to send the delivery text confirmation to the customer.",
    )

    # ------------------------------------------------------------
    # CONSTRAINTS
    # ------------------------------------------------------------

    @api.constrains("horizon_days")
    def _check_horizon_days(self):
        # A negative horizon would shift the replenishment horizon date into the
        # past (see stock.warehouse.orderpoint.get_horizon_days), silently making
        # reordering rules under-forecast demand. '0 days' is the just-in-time floor.
        for company in self:
            if company.horizon_days < 0:
                raise ValidationError(
                    _("The replenishment horizon cannot be negative.")
                )

    # ------------------------------------------------------------
    # CRUD METHODS
    # ------------------------------------------------------------

    @api.model_create_multi
    def create(self, vals_list):
        companies = super().create(vals_list)
        # The location ships archived; creating a company implies multi-company use, so reactivate it.
        inter_company_location = self.env.ref("stock.stock_location_inter_company")
        if not inter_company_location.active:
            inter_company_location.sudo().write({"active": True})
        # Provision on the whole batch at once: each hook is recordset-capable, so
        # N companies cost a constant number of INSERTs instead of N. Order encodes
        # dependencies (picking types need sequences, rules need picking types).
        companies_sudo = companies.sudo()
        companies_sudo._create_per_company_locations()
        companies_sudo._create_per_company_sequences()
        companies_sudo._create_per_company_picking_types()
        companies_sudo._create_per_company_rules()
        companies_sudo._set_per_company_inter_company_locations(inter_company_location)
        if modules.module.current_test:
            # Tests assume every company owns a warehouse; production provisions them
            # explicitly (bootstrap_first_warehouse, then create_missing_* backfills).
            # Use the single idempotent seam, not stock.warehouse.create directly.
            companies_sudo._create_warehouse()
        return companies

    # ------------------------------------------------------------
    # HELPER METHODS
    # ------------------------------------------------------------

    @api.model
    def _all_companies(self):
        """Every company, archived ones included.

        Provisioning must cover archived companies too: they still own records and
        may be reactivated later, so the ``create_missing_*`` backfills need them.
        """
        return self.env["res.company"].with_context(active_test=False).search([])

    @api.model
    def _companies_without(self, companies_having):
        """Return the companies not present in ``companies_having``.

        Shared by the ``create_missing_*`` backfills, which each provision a
        resource only for the companies that lack it.
        """
        return self._all_companies() - companies_having

    @api.model
    def _companies_with_property(self, model_name, field_name):
        """Companies that already resolve a default for the given property.

        A default with no ``company_id`` covers every company, so its presence means
        all are covered. Mapping ``company_id`` alone would drop that global default
        (``False`` -> empty recordset) and let the ``create_missing_*`` backfills
        duplicate a resource companies already resolve globally.
        """
        field = self.env["ir.model.fields"]._get(model_name, field_name)
        defaults = self.env["ir.default"].sudo()
        global_default = defaults.search_count(
            [("field_id", "=", field.id), ("company_id", "=", False)], limit=1
        )
        if global_default:
            return self._all_companies()
        return defaults.search([("field_id", "=", field.id)]).mapped("company_id")

    def _create_transit_location(self):
        """Create a per-company transit location for resupply routes between
        warehouses of the same company, avoiding the accounting entries a
        cross-company transfer would trigger.

        ``self`` may hold several companies (the ``create_missing_*`` backfills call
        these helpers on a multi-company recordset), so create in one batch and pair
        results back with ``zip``.
        """
        locations = self.env["stock.location"].create(
            [
                {
                    "name": _("Inter-warehouse transit"),
                    "usage": "transit",
                    "company_id": company.id,
                    "active": False,
                }
                for company in self
            ],
        )
        for company, location in zip(self, locations, strict=True):
            company.internal_transit_location_id = location.id
            # The env company must match the target company for the property write to
            # land on the right value, so this cannot be batched across companies.
            company.partner_id.with_company(company)._set_stock_property_locations(
                location
            )
        return locations

    def _create_property_location(self, name, usage, property_field):
        """Create one ``stock.location`` per company in ``self`` and register it as
        that company's default for the ``product.template`` property ``property_field``.

        Backs the inventory-loss and production locations, which differ only in
        name, usage and target property. ``self`` may be a multi-company recordset.
        """
        locations = self.env["stock.location"].create(
            [
                {
                    "name": name,
                    "usage": usage,
                    "company_id": company.id,
                }
                for company in self
            ],
        )
        for company, location in zip(self, locations, strict=True):
            self.env["ir.default"].set(
                "product.template",
                property_field,
                location.id,
                company_id=company.id,
            )
        return locations

    def _create_inventory_loss_location(self):
        return self._create_property_location(
            _("Inventory adjustment"), "inventory", "property_stock_inventory"
        )

    def _create_production_location(self):
        return self._create_property_location(
            _("Production"), "production", "property_stock_production"
        )

    def _create_scrap_sequence(self):
        return self.env["ir.sequence"].create(
            [
                {
                    "name": f"{company.name} Sequence scrap",
                    "code": "stock.scrap",
                    "company_id": company.id,
                    "prefix": "SP/",
                    "padding": 5,
                    "number_next": 1,
                    "number_increment": 1,
                }
                for company in self
            ],
        )

    def _create_warehouse(self):
        """Ensure every company in ``self`` owns its primary warehouse and return
        one warehouse per company, in ``self`` order (recordset-capable).

        The single seam through which a company acquires a warehouse, so the
        provisioning contract lives in one place. Idempotent: a company that already
        owns a warehouse keeps it instead of getting a duplicate (which would hit
        unique(name, company_id)), so callers need not know whether one was already
        provisioned.
        """
        Warehouse = self.env["stock.warehouse"]
        warehouse_by_company = {}
        # active_test=False: an archived warehouse still occupies its
        # unique(name/code, company_id) slots, so ignoring it made this
        # "idempotent" seam create a duplicate name and crash on the constraint.
        for warehouse in Warehouse.with_context(active_test=False).search(
            [("company_id", "in", self.ids)], order="id"
        ):
            warehouse_by_company.setdefault(warehouse.company_id.id, warehouse)
        companies_without = self.filtered(
            lambda company: company.id not in warehouse_by_company
        )
        # Route name/code through the warehouse's own unique-default generators
        # instead of the raw company name, so they de-duplicate against existing
        # (and same-batch) warehouses exactly like every other creation path.
        vals_list = []
        taken_names = defaultdict(set)
        taken_codes = defaultdict(set)
        for company in companies_without:
            name = Warehouse._generate_default_name(company, taken_names[company.id])
            code = Warehouse._generate_default_code(company, taken_codes[company.id])
            taken_names[company.id].add(name)
            taken_codes[company.id].add(code)
            vals_list.append(
                {
                    "name": name,
                    "code": code,
                    "company_id": company.id,
                    "partner_id": company.partner_id.id,
                },
            )
        new_warehouses = Warehouse.create(vals_list)
        for company, warehouse in zip(companies_without, new_warehouses, strict=True):
            warehouse_by_company[company.id] = warehouse
        return self.env["stock.warehouse"].union(
            *(warehouse_by_company[company.id] for company in self)
        )

    @api.model
    def bootstrap_first_warehouse(self):
        """Bootstrap a warehouse for the first company when the database has none yet.

        One-shot, not a per-company backfill: provisions a single warehouse only
        when none exists at all. Every other warehouse comes from an explicit
        ``_create_warehouse`` caller.
        """
        if self.env["stock.warehouse"].search_count([], limit=1):
            return
        self.env["res.company"].search([], limit=1)._create_warehouse()

    @api.model
    def create_missing_transit_location(self):
        company_without_transit = self._all_companies().filtered(
            lambda company: not company.internal_transit_location_id
        )
        company_without_transit._create_transit_location()

    @api.model
    def create_missing_inventory_loss_location(self):
        having = self._companies_with_property(
            "product.template", "property_stock_inventory"
        )
        self._companies_without(having)._create_inventory_loss_location()

    @api.model
    def create_missing_production_location(self):
        having = self._companies_with_property(
            "product.template", "property_stock_production"
        )
        self._companies_without(having)._create_production_location()

    @api.model
    def create_missing_scrap_sequence(self):
        having = (
            self.env["ir.sequence"]
            .search([("code", "=", "stock.scrap")])
            .mapped("company_id")
        )
        self._companies_without(having)._create_scrap_sequence()

    @api.model
    def create_missing_mail_template(self):
        """Backfill the delivery-confirmation mail template on companies that lack
        it (new companies get it from the field default). Invoked from
        ``data/mail_template_data.xml`` because the template is defined after
        ``data/stock_data.xml`` in the manifest, so it can't ride with the other
        ``create_missing_*`` calls there."""
        template_id = self._default_confirmation_mail_template()
        if not template_id:
            return
        self._all_companies().filtered(
            lambda company: not company.stock_mail_confirmation_template_id
        ).stock_mail_confirmation_template_id = template_id

    # The four ``_create_per_company_*`` hooks below run on a whole ``res.company``
    # recordset (``create`` calls them once on the batch), so each leaf provisioning
    # creates in one query, not one per company. Ordered locations -> sequences ->
    # picking types -> rules: picking types look up their sequence, rules their
    # picking type.
    def _create_per_company_locations(self):
        self._create_transit_location()
        self._create_inventory_loss_location()
        self._create_production_location()

    def _create_per_company_sequences(self):
        self._create_scrap_sequence()

    def _create_per_company_picking_types(self):
        """Extension point: modules that ship company-specific picking types
        (e.g. dropshipping) override this."""

    def _create_per_company_rules(self):
        """Extension point: modules that ship company-specific stock rules override this."""

    def _set_per_company_inter_company_locations(self, inter_company_location):
        """Point the stock customer/supplier properties of each company in ``self``
        and every other company at the shared inter-company transit location, in
        both directions. Only relevant once multi-company is enabled.

        Archived companies are included (``_all_companies``): a dormant company
        still owns records and may be reactivated, and without this wiring its
        cross-company transfers would route through the default customer/supplier
        locations instead of the shared transit location.
        """
        if not self.env.user.has_group("base.group_multi_company"):
            return
        all_companies = self._all_companies()
        for company in self:
            other_companies = all_companies - company
            other_companies.partner_id.with_company(
                company
            )._set_stock_property_locations(inter_company_location)
            for other_company in other_companies:
                # The env company must differ on every write for the company-dependent
                # property to land on the right value, so this stays a per-company loop.
                company.partner_id.with_company(
                    other_company
                )._set_stock_property_locations(inter_company_location)

    def _default_confirmation_mail_template(self):
        template = self.env.ref(
            "stock.mail_template_data_delivery_confirmation", raise_if_not_found=False
        )
        return template.id if template else False

    def _get_text_validation(self, confirmation_type):
        self.ensure_one()
        return bool(
            self.stock_text_confirmation
            and self.stock_confirmation_type == confirmation_type
        )
