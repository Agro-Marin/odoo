from odoo import _, api, fields, models
from odoo.exceptions import AccessError, UserError, ValidationError
from odoo.fields import Domain
from odoo.tools import SQL, is_html_empty


class ProductTemplate(models.Model):
    _name = "product.template"
    _inherit = ["product.template", "mixin.pos.load"]

    # FIELDS
    # ------------------------------------------------------------------

    available_in_pos = fields.Boolean(
        string="Available in POS",
        help="Check if you want this product to appear in the Point of Sale.",
        default=False,
    )
    to_weight = fields.Boolean(
        string="To Weigh With Scale",
        help="Check if the product should be weighted using the hardware scale integration.",
    )
    pos_categ_ids = fields.Many2many(
        "pos.category",
        string="Point of Sale Category",
        help="Category used in the Point of Sale.",
    )
    public_description = fields.Html(string="Product Description", translate=True)
    pos_optional_product_ids = fields.Many2many(
        comodel_name="product.template",
        relation="pos_product_optional_rel",
        column1="src_id",
        column2="dest_id",
        string="POS Optional Products",
        help="Optional products are suggested when customers add items to their cart (e.g., adding a burger suggests cold drinks or fries).",
    )
    color = fields.Integer(
        "Color Index", compute="_compute_color", store=True, readonly=False
    )
    pos_sequence = fields.Integer(
        string="POS Sequence",
        help="Determine the display order in the POS Terminal",
        copy=False,
    )

    # CONSTRAINT METHODS
    # ------------------------------------------------------------------

    @api.constrains("available_in_pos")
    def _check_available_in_pos(self):
        withdrawn = self.filtered(lambda template: not template.available_in_pos)
        if not withdrawn:
            return
        combo_item = (
            self.env["product.combo.item"]
            .sudo()
            .search(
                [("product_id", "in", withdrawn.product_variant_ids.ids)],
                limit=1,
            )
        )
        if combo_item:
            raise ValidationError(
                _(
                    "You must first remove this product from the %s combo",
                    combo_item.combo_id.name,
                )
            )

    @api.constrains("pos_optional_product_ids")
    def _check_pos_optional_product_ids(self):
        for template in self:
            if template in template.pos_optional_product_ids:
                raise ValidationError(
                    _(
                        "%s cannot be suggested as an optional product for itself.",
                        template.display_name,
                    )
                )

    def _check_unused_in_pos(self):
        if self._is_blocked_by_open_pos_session():
            raise UserError(
                _(
                    "Hold up! Archiving products while POS sessions are active is like pulling a plate mid-meal.\n"
                    "Make sure to close all sessions first to avoid any issues.",
                )
            )

    def _check_is_special_product(self):
        special = self._filtered_pos_special_products()
        if special:
            raise UserError(
                _(
                    "You cannot archive or delete %s: it is set as a special product "
                    "in a Point of Sale configuration. Please change the configuration first.",
                    special[0].display_name,
                )
            )

    # CRUD METHODS
    # ------------------------------------------------------------------

    @api.model_create_multi
    def create(self, vals_list):
        self._update_public_description_vals(vals_list)
        self._update_pos_sequence_vals(vals_list)
        for vals in vals_list:
            self._update_available_in_pos_vals(vals)
        return super().create(vals_list)

    def write(self, vals):
        self._update_public_description_vals([vals])
        self._update_available_in_pos_vals(vals)
        if "active" in vals and not vals["active"]:
            self._check_unused_in_pos()
            self._check_is_special_product()
        return super().write(vals)

    @api.ondelete(at_uninstall=False)
    def _unlink_except_open_session(self):
        if self._is_blocked_by_open_pos_session():
            raise UserError(
                _(
                    "To delete a product, make sure all point of sale sessions are closed.\n\n"
                    "Deleting a product available in a session would be like attempting to snatch a hamburger from a customer’s hand mid-bite; chaos will ensue as ketchup and mayo go flying everywhere!",
                )
            )

    @api.ondelete(at_uninstall=False)
    def _unlink_except_special_product(self):
        self._check_is_special_product()

    # COMPUTE METHODS
    # ------------------------------------------------------------------

    @api.depends("pos_categ_ids")
    def _compute_color(self):
        for product in self:
            if product.pos_categ_ids:
                product.color = product.pos_categ_ids[0].color
            else:
                product.color = product.color or 0

    # ONCHANGE METHODS
    # ------------------------------------------------------------------

    @api.onchange("sale_ok")
    def _onchange_sale_ok(self):
        if not self.sale_ok:
            self.available_in_pos = False

    @api.onchange("available_in_pos")
    def _onchange_available_in_pos(self):
        if self.available_in_pos and not self.sale_ok:
            self.sale_ok = True

    # POS LOADING METHODS
    # ------------------------------------------------------------------

    @api.model
    def _load_pos_data_domain(self, data, config):
        domain = [
            *self._check_company_domain(config.company_id),
            ("available_in_pos", "=", True),
            ("sale_ok", "=", True),
        ]
        if config.limit_categories:
            domain += [("pos_categ_ids", "in", config.iface_available_categ_ids.ids)]
        return domain

    @api.model
    def _load_pos_data_fields(self, config):
        return [
            "id",
            "display_name",
            "standard_price",
            "categ_id",
            "pos_categ_ids",
            "taxes_id",
            "barcode",
            "name",
            "list_price",
            "is_favorite",
            "default_code",
            "to_weight",
            "uom_id",
            "description_sale",
            "description",
            "tracking",
            "type",
            "service_tracking",
            "is_storable",
            "write_date",
            "color",
            "pos_sequence",
            "available_in_pos",
            "attribute_line_ids",
            "active",
            "image_128",
            "combo_ids",
            "product_variant_ids",
            "public_description",
            "pos_optional_product_ids",
            "sequence",
            "product_tag_ids",
        ]

    @api.model
    def _load_pos_data_search_read(self, data, config):
        domain = self._load_pos_data_domain(data, config)
        limit_count = config.get_limited_product_count()
        if limit_count and self.env.context.get("pos_limited_loading", True):
            dated_domain = self._add_server_date_to_domain(domain)
            if dated_domain is False:
                return []
            recent_ids = self._get_ids_ranked_for_pos(dated_domain, limit_count)
            products = self._load_product_with_domain([("id", "in", recent_ids)])
        else:
            products = self._load_product_with_domain(domain)

        combos = products.filtered(lambda product: product.type == "combo")
        products |= combos.combo_ids.combo_item_ids.product_id.product_tmpl_id
        products |= (
            config._get_special_products()
            .filtered(
                lambda product: (
                    not product.sudo().company_id
                    or product.sudo().company_id == self.env.company
                )
            )
            .product_tmpl_id
        )
        products |= products.pos_optional_product_ids
        if data.get("pos.order.line"):
            products |= (
                self.env["product.product"]
                .browse([line["product_id"] for line in data["pos.order.line"]])
                .product_tmpl_id
            )

        return self._load_pos_data_read(products, config)

    @api.model
    def _load_pos_data_read(self, records, config):
        records = records._with_pos_company(config)
        rows = super()._load_pos_data_read(records, config)
        self._update_rows_with_config_currency(rows, config)
        self._update_rows_with_company_taxes(rows, config)
        self._add_archived_combinations(rows)
        for row in rows:
            row["image_128"] = bool(row["image_128"])
        return rows

    @api.model
    def load_product_from_pos(self, config_id, domain, offset=0, limit=0):
        config = self.env["pos.config"].browse(config_id)
        config.check_access("read")
        domain = Domain(domain)
        load_archived = self.env.context.get("load_archived", False)
        product_tmpls = self._load_product_with_domain(
            domain, load_archived, offset, limit
        )
        combos = product_tmpls.filtered(lambda template: template.type == "combo")
        product_tmpls |= combos.combo_ids.combo_item_ids.product_id.product_tmpl_id
        products = product_tmpls.product_variant_ids

        return {
            **self._get_pos_pricelist_data(product_tmpls, products, config),
            **self._get_pos_combo_data(product_tmpls, config),
            **self._get_pos_attribute_data(product_tmpls, config),
            **self._get_pos_packaging_data(products, domain, config),
            **self._get_pos_tax_data(product_tmpls, config),
            "product.product": self.env["product.product"]._load_pos_data_read(
                products.with_context(display_default_code=False), config
            ),
            "product.template": self._load_pos_data_read(product_tmpls, config),
        }

    @api.model
    def _get_ids_ranked_for_pos(self, domain, limit):
        query = self._search(domain, bypass_access=True)
        sql = SQL(
            """
                WITH pm AS (
                    SELECT pp.product_tmpl_id,
                        MAX(sml.write_date) date
                    FROM stock_move_line sml
                    JOIN product_product pp ON sml.product_id = pp.id
                    GROUP BY pp.product_tmpl_id
                )
                SELECT product_template.id
                    FROM %s
                LEFT JOIN pm ON product_template.id = pm.product_tmpl_id
                    WHERE %s
                ORDER BY product_template.is_favorite DESC NULLS LAST,
                    CASE WHEN product_template.type = 'service' THEN 1 ELSE 0 END DESC,
                    pm.date DESC NULLS LAST,
                    product_template.write_date DESC
                LIMIT %s
            """,
            query.from_clause,
            query.where_clause or SQL("TRUE"),
            limit,
        )
        return [row[0] for row in self.env.execute_query(sql)]

    def _load_product_with_domain(self, domain, load_archived=False, offset=0, limit=0):
        return self.with_context(
            display_default_code=False,
            active_test=not load_archived,
            bin_size=True,
        ).search(
            self._add_server_date_to_domain(domain),
            order="sequence,default_code,name",
            offset=offset,
            limit=limit or False,
        )

    @api.model
    def _get_pos_pricelist_data(self, product_tmpls, products, config):
        # asks the config directly: the pricelists, the company and the two field
        # lists are all its own, so the guard against an absent session goes too
        return config.get_pos_ui_product_pricelist_item_by_product(
            product_tmpls.ids, products.ids
        )

    @api.model
    def _get_pos_combo_data(self, product_tmpls, config):
        combos = product_tmpls.combo_ids
        return {
            "product.combo": self.env["product.combo"]._load_pos_data_read(
                combos, config
            ),
            "product.combo.item": self.env["product.combo.item"]._load_pos_data_read(
                combos.combo_item_ids, config
            ),
        }

    @api.model
    def _get_pos_attribute_data(self, product_tmpls, config):
        attribute_lines = product_tmpls.attribute_line_ids
        attribute_values = attribute_lines.product_template_value_ids
        exclusion = self.env["product.template.attribute.exclusion"]
        exclusions = attribute_values.exclude_for | exclusion.search(
            [("product_tmpl_id", "in", product_tmpls.ids)]
        )
        line_model = self.env["product.template.attribute.line"]
        value_model = self.env["product.template.attribute.value"]
        return {
            "product.template.attribute.line": line_model._load_pos_data_read(
                attribute_lines, config
            ),
            "product.template.attribute.value": value_model._load_pos_data_read(
                attribute_values, config
            ),
            "product.template.attribute.exclusion": exclusion._load_pos_data_read(
                exclusions, config
            ),
        }

    @api.model
    def _get_pos_packaging_data(self, products, domain, config):
        product_uom = self.env["product.uom"]
        packaging_domain = Domain(
            "product_id", "in", products.ids
        ) | self._get_domain_scanned_barcodes(domain)
        return {
            "product.uom": product_uom._load_pos_data_read(
                product_uom.search(packaging_domain), config
            ),
        }

    @api.model
    def _get_domain_scanned_barcodes(self, domain):
        # each condition is mirrored with its own operator rather than flattened
        # into one list: a scalar under "=" is a barcode, not a sequence of them.
        # "ilike" is deliberately not mirrored -- the POS search box sends one on
        # every keystroke, and a substring match over every packaging is unbounded
        conditions = [
            Domain("barcode", condition.operator, condition.value)
            for condition in domain.iter_conditions()
            if condition.field_expr.endswith("barcode")
            and condition.operator in ("=", "in")
        ]
        return Domain.OR(conditions) if conditions else Domain.FALSE

    @api.model
    def _get_pos_tax_data(self, product_tmpls, config):
        account_tax = self.env["account.tax"]
        tax_domain = Domain(
            account_tax._check_company_domain(config.company_id)
        ) & Domain("id", "in", product_tmpls.taxes_id.ids)
        return {
            "account.tax": account_tax._load_pos_data_read(
                account_tax.search(tax_domain), config
            ),
        }

    @api.model
    def _update_rows_with_config_currency(self, rows, config):
        if not rows:
            return
        company = config.company_id
        target = config.currency_id
        today = fields.Date.today()
        # list_price and standard_price do not share a currency: product.template
        # prices the first against main-company currency and the second against the
        # reading company's, and either is the product's own company when it has one
        templates = self.browse([row["id"] for row in rows])._with_pos_company(config)
        currencies_by_id = {
            template.id: (template.currency_id, template.cost_currency_id)
            for template in templates
        }
        for row in rows:
            list_currency, cost_currency = currencies_by_id[row["id"]]
            if list_currency != target:
                row["list_price"] = list_currency._convert(
                    row["list_price"], target, company, today
                )
            if cost_currency != target:
                row["standard_price"] = cost_currency._convert(
                    row["standard_price"], target, company, today
                )

    @api.model
    def _update_rows_with_company_taxes(self, rows, config):
        company = config.company_id
        if not company.parent_id:
            return
        account_tax = self.env["account.tax"]
        taxes_by_company = self._get_taxes_by_company(
            account_tax.search(account_tax._check_company_domain(company))
        )
        if len(taxes_by_company) < 2:
            return
        for row in rows:
            if len(row["taxes_id"]) > 1:
                row["taxes_id"] = self._get_tax_ids_of_nearest_company(
                    row["taxes_id"], taxes_by_company, company
                )

    @api.model
    def _get_taxes_by_company(self, taxes):
        # the membership account_tax._serves_company asks about, indexed once
        taxes_by_company = {}
        for tax in taxes:
            for company_id in tax.sudo().company_ids.ids:
                taxes_by_company.setdefault(company_id, set()).add(tax.id)
        return taxes_by_company

    @api.model
    def _get_tax_ids_of_nearest_company(self, tax_ids, taxes_by_company, company):
        matching = []
        while not matching and company:
            owned = taxes_by_company.get(company.id, frozenset())
            matching = [tax_id for tax_id in tax_ids if tax_id in owned]
            company = company.sudo().parent_id
        return matching

    def _add_archived_combinations(self, products):
        product_data = {product["id"]: product for product in products}
        for product_tmpl in self.browse(product_data.keys()):
            product = product_data[product_tmpl.id]
            if not product_tmpl.attribute_line_ids:
                product["_archived_combinations"] = []
                continue
            # the two halves the terminal needs, not _get_attribute_exclusions:
            # that also builds parent_exclusions, parent_combination,
            # parent_product_name and mapped_attribute_names, all discarded here,
            # and mapped_attribute_names alone is more than half its cost
            combinations = product_tmpl._get_archived_combinations()
            exclusions = product_tmpl._complete_inverse_exclusions(
                product_tmpl._get_own_attribute_exclusions()
            )
            for ptav_id, ptav_ids in exclusions.items():
                combinations.extend((ptav_id, other) for other in ptav_ids)
            product["_archived_combinations"] = combinations

    # POS TERMINAL METHODS
    # ------------------------------------------------------------------

    def set_pos_favorite(self, is_favorite):
        self.check_singleton()
        if not self.env.user.has_group("point_of_sale.group_pos_user"):
            raise AccessError(_("Only Point of Sale users can change a POS favorite."))
        if not self.available_in_pos:
            raise AccessError(
                _(
                    "%s is not available in the Point of Sale, so it cannot be "
                    "marked as a favorite there.",
                    self.display_name,
                )
            )
        self.sudo().is_favorite = bool(is_favorite)
        return self.is_favorite

    def create_product_variant_from_pos(self, attribute_value_ids, config_id):
        self.check_singleton()
        config = self.env["pos.config"].browse(config_id)
        config.check_access("read")
        attribute_values = self.env["product.template.attribute.value"].browse(
            attribute_value_ids
        )
        product_variant = self._create_product_variant(attribute_values)
        return {
            "product.product": self.env["product.product"]._load_pos_data_read(
                product_variant, config
            ),
        }

    def get_product_info_pos(
        self, price, quantity, pos_config_id, product_variant_id=False
    ):
        self.check_singleton()
        config = self.env["pos.config"].browse(pos_config_id)
        config.check_access("read")
        product_variant = (
            self.env["product.product"].browse(product_variant_id)
            if product_variant_id
            else self.env["product.product"]
        )
        template_or_variant = product_variant or self.product_variant_id

        return {
            "all_prices": self._get_pos_price_info(
                price, quantity, config, product_variant or self
            ),
            "pricelists": self._get_pos_pricelist_info(
                config, template_or_variant, quantity
            ),
            "warehouses": self._get_pos_warehouse_info(config, template_or_variant),
            "suppliers": self._get_pos_supplier_info(quantity),
            "variants": self._get_pos_variant_info(),
            "optional_products": self.pos_optional_product_ids.read(
                ["id", "name", "list_price"]
            ),
        }

    def _get_pos_price_info(self, price, quantity, config, product):
        taxes = self._get_taxes_of_nearest_company(config.company_id)
        computed = taxes.sudo().compute_all(
            price, config.currency_id, quantity, product.sudo()
        )
        per_unit = quantity or 1

        grouped_taxes = {}
        for tax in computed["taxes"]:
            amount = tax["amount"] / per_unit if quantity else 0
            if tax["id"] in grouped_taxes:
                grouped_taxes[tax["id"]]["amount"] += amount
            else:
                grouped_taxes[tax["id"]] = {"name": tax["name"], "amount": amount}

        return {
            "price_without_tax": (
                computed["total_excluded"] / per_unit if quantity else 0
            ),
            "price_with_tax": computed["total_included"] / per_unit if quantity else 0,
            "tax_details": list(grouped_taxes.values()),
        }

    def _get_taxes_of_nearest_company(self, company):
        return self.taxes_id.browse(
            self._get_tax_ids_of_nearest_company(
                self.taxes_id.ids, self._get_taxes_by_company(self.taxes_id), company
            )
        )

    def _get_pos_pricelist_info(self, config, product, quantity):
        pricelists = (
            config.available_pricelist_ids
            if config.use_pricelist
            else config.pricelist_id
        )
        if not pricelists:
            return []
        price_by_pricelist_id = pricelists._price_get(product, quantity)
        return [
            {"name": pricelist.name, "price": price_by_pricelist_id[pricelist.id]}
            for pricelist in pricelists
        ]

    def _get_pos_warehouse_info(self, config, product):
        warehouses = self.env["stock.warehouse"].search(
            [("company_id", "=", config.company_id.id)]
        )
        pos_warehouse_id = config.picking_type_id.warehouse_id.id
        warehouse_info = []
        for warehouse in warehouses:
            in_warehouse = product.with_context(warehouse_id=warehouse.id)
            warehouse_info.append(
                {
                    "id": warehouse.id,
                    "name": warehouse.name,
                    "available_quantity": in_warehouse.qty_available,
                    "qty_free": in_warehouse.qty_free,
                    "forecasted_quantity": in_warehouse.qty_available_virtual,
                    "uom": product.uom_name,
                }
            )
        if pos_warehouse_id:
            warehouse_info.sort(key=lambda info: info["id"] != pos_warehouse_id)
        return warehouse_info

    def _get_pos_supplier_info(self, quantity):
        today = fields.Date.today()
        supplier_info = {}
        for seller in self.seller_ids:
            if seller.partner_id.id in supplier_info:
                continue
            if (
                (seller.date_start and seller.date_start > today)
                or (seller.date_end and seller.date_end < today)
                or seller.min_qty > quantity
            ):
                continue
            supplier_info[seller.partner_id.id] = {
                "id": seller.id,
                "name": seller.partner_id.name,
                "delay": seller.delay,
                "price": seller.price,
            }
        return list(supplier_info.values())

    def _get_pos_variant_info(self):
        return [
            {
                "name": attribute_line.attribute_id.name,
                "values": [
                    {"name": attr_name, "search": f"{self.name} {attr_name}"}
                    for attr_name in attribute_line.value_ids.mapped("name")
                ],
            }
            for attribute_line in self.attribute_line_ids
        ]

    # HELPER METHODS
    # ------------------------------------------------------------------

    @api.model
    def _update_available_in_pos_vals(self, vals):
        # _onchange_sale_ok clears this in the form; every other writer -- import,
        # RPC, migration -- could leave a product flagged for the POS that the POS
        # domain excludes, so it silently stops loading with nothing on the record
        # saying why
        if "sale_ok" in vals and not vals["sale_ok"]:
            vals["available_in_pos"] = False

    @api.model
    def _update_public_description_vals(self, vals_list):
        for vals in vals_list:
            description = vals.get("public_description")
            if description and is_html_empty(description):
                vals["public_description"] = ""

    @api.model
    def _update_pos_sequence_vals(self, vals_list):
        pending = [vals for vals in vals_list if not vals.get("pos_sequence")]
        if not pending:
            return
        self.flush_model(["pos_sequence"])
        rows = self.env.execute_query(
            SQL("SELECT MAX(pos_sequence) FROM %s", SQL.identifier(self._table))
        )
        next_sequence = (rows[0][0] or 0) + 1
        for offset, vals in enumerate(pending):
            vals["pos_sequence"] = next_sequence + offset

    def _filtered_pos_special_products(self):
        # Two different questions, and the guard wants both. Since da0e178100f
        # _get_special_products honours self, so the configs answer "what any
        # config actually uses" -- which the empty recordset cannot -- and the
        # empty recordset answers "the global defaults", which the configs cannot
        # once every one of them has cleared its tip_product_id.
        config = self.env["pos.config"].sudo()
        special = (
            config.search([])._get_special_products() | config._get_special_products()
        )
        return self & special.product_tmpl_id

    def _is_blocked_by_open_pos_session(self):
        return bool(
            any(self.mapped("available_in_pos"))
            and self.env["pos.session"]
            .sudo()
            .search_count([("state", "!=", "closed")], limit=1)
        )
