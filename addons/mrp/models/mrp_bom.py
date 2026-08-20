# Part of Odoo. See LICENSE file for full copyright and licensing details.

from collections import defaultdict
from itertools import starmap

from markupsafe import Markup

from odoo import _, api, fields, models
from odoo.exceptions import UserError, ValidationError
from odoo.fields import Command, Domain
from odoo.tools import float_compare, formatLang
from odoo.tools.misc import OrderedSet, clean_context


class MrpBom(models.Model):
    """Defines bills of material for a product or a product template"""

    _name = "mrp.bom"
    _description = "Bill of Material"
    _inherit = ["mixin.mail.thread", "mixin.product.catalog"]
    _rec_name = "product_tmpl_id"
    _rec_names_search = ["product_tmpl_id", "code"]
    _order = "sequence, id"
    _check_company_auto = True

    def _get_default_product_uom_id(self):
        return self.env["uom.uom"].search([], limit=1, order="id").id

    code = fields.Char("Reference")
    active = fields.Boolean("Active", default=True)
    type = fields.Selection(
        [("normal", "Manufacture this product"), ("phantom", "Kit")],
        "BoM Type",
        default="normal",
        required=True,
    )
    product_tmpl_id = fields.Many2one(
        "product.template",
        "Product",
        check_company=True,
        index=True,
        domain="[('type', '=', 'consu')]",
        required=True,
    )
    product_id = fields.Many2one(
        "product.product",
        "Product Variant",
        check_company=True,
        index=True,
        domain="['&', ('product_tmpl_id', '=', product_tmpl_id), ('type', '=', 'consu')]",
        help="If a product variant is defined the BOM is available only for this product.",
    )
    bom_line_ids = fields.One2many("mrp.bom.line", "bom_id", "BoM Lines", copy=True)
    byproduct_ids = fields.One2many(
        "mrp.bom.byproduct", "bom_id", "By-products", copy=True
    )
    product_qty = fields.Float(
        "Quantity",
        default=1.0,
        digits="Product Unit",
        required=True,
        help="This should be the smallest quantity that this product can be produced in. If the BOM contains operations, make sure the work center capacity is accurate.",
    )
    product_uom_id = fields.Many2one(
        "uom.uom",
        "Unit",
        default=_get_default_product_uom_id,
        required=True,
        help="Unit of Measure (Unit of Measure) is the unit of measurement for the inventory control",
    )
    sequence = fields.Integer("Sequence")
    operation_ids = fields.One2many(
        "mrp.routing.workcenter", "bom_id", "Operations", copy=True
    )
    operation_count = fields.Integer(
        "Operations Count", compute="_compute_operation_count"
    )
    show_copy_operations_button = fields.Boolean(
        compute="_compute_show_copy_operations_button",
        help="Technical field used to control the visibility of the 'Copy Existing Operations' button.",
    )
    ready_to_produce = fields.Selection(
        [
            ("all_available", " When all components are available"),
            ("asap", "When components for 1st operation are available"),
        ],
        string="Manufacturing Readiness",
        default="all_available",
        required=True,
    )
    picking_type_id = fields.Many2one(
        "stock.picking.type",
        "Operation Type",
        domain="[('code', '=', 'mrp_operation')]",
        check_company=True,
        help="When a procurement has a ‘produce’ route with a operation type set, it will try to create "
        "a Manufacturing Order for that product using a BoM of the same operation type.If not,"
        "the operation type is not taken into account in the BoM search. That allows "
        "to define stock rules which trigger different manufacturing orders with different BoMs.",
    )
    company_id = fields.Many2one(
        "res.company", "Company", index=True, default=lambda self: self.env.company
    )
    consumption = fields.Selection(
        [
            ("flexible", "Allowed"),
            ("warning", "Allowed with warning"),
            ("strict", "Blocked"),
        ],
        help="Defines if you can consume more or less components than the quantity defined on the BoM:\n"
        "  * Allowed: allowed for all manufacturing users.\n"
        "  * Allowed with warning: allowed for all manufacturing users with summary of consumption differences when closing the manufacturing order.\n"
        "  Note that in the case of component Highlight Consumption, where consumption is registered manually exclusively, consumption warnings will still be issued when appropriate also.\n"
        "  * Blocked: only a manager can close a manufacturing order when the BoM consumption is not respected.",
        default="warning",
        string="Flexible Consumption",
        required=True,
    )
    possible_product_template_attribute_value_ids = fields.Many2many(
        "product.template.attribute.value",
        compute="_compute_possible_product_template_attribute_value_ids",
    )
    allow_operation_dependencies = fields.Boolean(
        "Operation Dependencies",
        help="Create operation level dependencies that will influence both planning and the status of work orders upon MO confirmation. If this feature is ticked, and nothing is specified, Odoo will assume that all operations can be started simultaneously.",
    )
    produce_delay = fields.Integer(
        "Manufacturing Lead Time",
        default=0,
        help="Average lead time in days to manufacture this product. In the case of multi-level BOM, the manufacturing lead times of the components will be added. In case the product is subcontracted, this can be used to determine the date at which components should be sent to the subcontractor.",
    )
    days_to_prepare_mo = fields.Integer(
        string="Days to prepare Manufacturing Order",
        default=0,
        help="Create and confirm Manufacturing Orders this many days in advance, to have enough time to replenish components or manufacture semi-finished products.",
    )
    show_set_bom_button = fields.Boolean(compute="_compute_show_set_bom_button")
    batch_size = fields.Float(
        "Batch Size",
        default=1.0,
        digits="Product Unit",
        help="All automatically generated manufacturing orders for this product will be of this size.",
    )
    enable_batch_size = fields.Boolean(default=False)

    _qty_positive = models.Constraint(
        "check (product_qty > 0)",
        "The quantity to produce must be positive!",
    )

    @api.depends(
        "product_tmpl_id.attribute_line_ids.value_ids",
        "product_tmpl_id.attribute_line_ids.attribute_id.create_variant",
        "product_tmpl_id.attribute_line_ids.product_template_value_ids.ptav_active",
    )
    def _compute_possible_product_template_attribute_value_ids(self):
        for bom in self:
            bom.possible_product_template_attribute_value_ids = bom.product_tmpl_id.valid_product_template_attribute_line_ids.product_template_value_ids._only_active()

    def _reset_variant_data(self):
        """Clear every "Apply on Variants" restriction, warning if any existed.

        Shared by the two onchanges that change which product a BoM describes:
        the restrictions name attribute values of the *old* product and mean
        nothing once it changes.
        """
        self.ensure_one()
        had_variant_data = (
            self.bom_line_ids.bom_product_template_attribute_value_ids
            or self.operation_ids.bom_product_template_attribute_value_ids
            or self.byproduct_ids.bom_product_template_attribute_value_ids
        )
        self.bom_line_ids.bom_product_template_attribute_value_ids = False
        self.operation_ids.bom_product_template_attribute_value_ids = False
        self.byproduct_ids.bom_product_template_attribute_value_ids = False
        if not had_variant_data:
            return None
        return {
            "warning": {
                "title": _("Warning"),
                "message": _(
                    "Changing the product or variant will permanently reset all previously encoded variant-related data."
                ),
            }
        }

    @api.onchange("product_id")
    def _onchange_product_id(self):
        if self.product_id:
            return self._reset_variant_data()
        return None

    @api.constrains("product_uom_id", "product_tmpl_id", "product_id")
    def _check_product_uom_id_category(self):
        """A BoM must be quantified in a unit that measures its own product.

        `product_qty` is expressed in `product_uom_id` while the product it
        produces is measured in `product_tmpl_id.uom_id`; every explosion,
        report and cost roll-up converts between the two. Nothing else pins
        them together: `create` aligns the unit only when it is *not* given
        (see the override below), the field carries no domain, and a
        cross-category value silently turned every such conversion into a
        scale by the ratio of two unrelated factors -- e.g. a subcontracted
        BoM stated in kg for a product sold in Units wrote a `standard_price`
        off by 1000 (`mrp_subcontracting_account._compute_bom_price`).
        """
        for bom in self:
            product_uom = bom.product_tmpl_id.uom_id
            if (
                bom.product_uom_id
                and product_uom
                and not bom.product_uom_id._has_common_reference(product_uom)
            ):
                raise ValidationError(
                    _(
                        "The bill of materials for %(product)s is quantified in"
                        " %(unit)s, which does not measure the same thing as the"
                        " product's own unit %(product_unit)s.",
                        product=bom.product_tmpl_id.display_name,
                        unit=bom.product_uom_id.display_name,
                        product_unit=product_uom.display_name,
                    )
                )

    @api.constrains("active", "product_id", "product_tmpl_id", "bom_line_ids")
    def _check_bom_cycle(self):
        subcomponents_dict = {}

        def _check_cycle(components, finished_products):
            """Raise if the components are part of the finished products (-> cycle).

            Components that have a BoM are recursed into with their subcomponents.

            :raises ValidationError: naming the product variants forming the cycle
            """
            products_to_find = self.env["product.product"]

            for component in components:
                if component in finished_products:
                    names = finished_products.mapped("display_name")
                    raise ValidationError(
                        _(
                            "The current configuration is incorrect because it would create a cycle between these products: %s.",
                            ", ".join(names),
                        )
                    )
                if component not in subcomponents_dict:
                    products_to_find |= component

            bom_find_result = self._bom_find(products_to_find)
            for component in components:
                if component not in subcomponents_dict:
                    bom = bom_find_result[component]
                    subcomponents = bom.bom_line_ids.filtered(
                        lambda l, component=component: not l._skip_bom_line(component)
                    ).product_id
                    subcomponents_dict[component] = subcomponents
                subcomponents = subcomponents_dict[component]
                if subcomponents:
                    _check_cycle(subcomponents, finished_products | component)

        boms_to_check = self
        if self.bom_line_ids.product_id:
            boms_to_check |= self.search(
                Domain.OR(
                    self._bom_find_domain(product)
                    for product in self.bom_line_ids.product_id
                )
            )

        for bom in boms_to_check:
            if not bom.active:
                continue
            finished_products = (
                bom.product_id or bom.product_tmpl_id.product_variant_ids
            )
            if bom.bom_line_ids.bom_product_template_attribute_value_ids:
                grouped_by_components = defaultdict(lambda: self.env["product.product"])
                for finished in finished_products:
                    components = bom.bom_line_ids.filtered(
                        lambda l, finished=finished: not l._skip_bom_line(finished)
                    ).product_id
                    grouped_by_components[components] |= finished
                for components, finished in grouped_by_components.items():
                    _check_cycle(components, finished)
            else:
                _check_cycle(bom.bom_line_ids.product_id, finished_products)

    @api.constrains(
        "product_id",
        "product_tmpl_id",
        "bom_line_ids",
        "byproduct_ids",
        "operation_ids",
    )
    def _check_bom_lines(self):
        for bom in self:
            apply_variants = (
                bom.bom_line_ids.bom_product_template_attribute_value_ids
                | bom.operation_ids.bom_product_template_attribute_value_ids
                | bom.byproduct_ids.bom_product_template_attribute_value_ids
            )
            if bom.product_id and apply_variants:
                raise ValidationError(
                    _(
                        "You cannot use the 'Apply on Variant' functionality and simultaneously create a BoM for a specific variant."
                    )
                )
            for ptav in apply_variants:
                if ptav.product_tmpl_id != bom.product_tmpl_id:
                    raise ValidationError(
                        _(
                            "The attribute value %(attribute)s set on product %(product)s does not match the BoM product %(bom_product)s.",
                            attribute=ptav.display_name,
                            product=ptav.product_tmpl_id.display_name,
                            bom_product=bom.product_tmpl_id.display_name,
                        )
                    )
            for byproduct in bom.byproduct_ids:
                if bom.product_id:
                    same_product = bom.product_id == byproduct.product_id
                else:
                    same_product = (
                        bom.product_tmpl_id == byproduct.product_id.product_tmpl_id
                    )
                if same_product:
                    raise ValidationError(
                        _(
                            "By-product %s should not be the same as BoM product.",
                            bom.display_name,
                        )
                    )
                if byproduct.cost_share < 0:
                    raise ValidationError(
                        _("By-products cost shares must be positive.")
                    )
            for product in bom.product_tmpl_id.product_variant_ids:
                total_variant_cost_share = sum(
                    bom.byproduct_ids.filtered(
                        lambda bp, product=product: (
                            not bp._skip_byproduct_line(product)
                            and not bp.product_uom_id.is_zero(bp.product_qty)
                        )
                    ).mapped("cost_share")
                )
                if float_compare(total_variant_cost_share, 100, precision_digits=2) > 0:
                    raise ValidationError(
                        _(
                            "The total cost share for a BoM's by-products cannot exceed 100."
                        )
                    )

    @api.onchange("bom_line_ids", "product_qty", "product_id", "product_tmpl_id")
    def onchange_bom_structure(self):
        if (
            self.type == "phantom"
            and self._origin
            and self.env["stock.move"].search_count(
                [("bom_line_id", "in", self._origin.bom_line_ids.ids)], limit=1
            )
        ):
            return {
                "warning": {
                    "title": _("Warning"),
                    "message": _(
                        "The product has already been used at least once, editing its structure may lead to undesirable behaviours. "
                        "You should rather archive the product and create a new one with a new bill of materials."
                    ),
                }
            }
        return None

    @api.onchange("product_tmpl_id")
    def onchange_product_tmpl_id(self):
        if self.product_tmpl_id:
            default_uom_id = self.env.context.get("default_product_uom_id")
            # Avoids updating the BoM's UoM in case a specific UoM was passed through as a default value.
            if self.product_uom_id.id != default_uom_id:
                self.product_uom_id = self.product_tmpl_id.uom_id.id
            if self.product_id.product_tmpl_id != self.product_tmpl_id:
                self.product_id = False
            warning = self._reset_variant_data()

            domain = [("product_tmpl_id", "=", self.product_tmpl_id.id)]
            if self.id.origin:
                domain.append(("id", "!=", self.id.origin))
            number_of_bom_of_this_product = self.env["mrp.bom"].search_count(domain)
            if (
                number_of_bom_of_this_product
            ):  # add a reference to the bom if there is already a bom for this product
                self.code = _(
                    "%(product_name)s (new) %(number_of_boms)s",
                    product_name=self.product_tmpl_id.name,
                    number_of_boms=number_of_bom_of_this_product,
                )
            if warning:
                return warning
        return None

    @api.model_create_multi
    def create(self, vals_list):
        for values in vals_list:
            # Keep the BoM UoM in the same category as its product when it isn't
            # given explicitly (mirrors mrp.bom.line.create). The field default is
            # the first uom.uom ("Units"), so a BoM created in code for a product
            # measured in e.g. m² would otherwise keep "Units" and every UoM
            # conversion in the BoM/MO reports and explode() would raise.
            if values.get("product_tmpl_id") and "product_uom_id" not in values:
                values["product_uom_id"] = (
                    self.env["product.template"]
                    .browse(values["product_tmpl_id"])
                    .uom_id.id
                )
        res = super().create(vals_list)
        # Checks if the BoM was created from a Manufacturing Order (through Generate BoM action).
        parent_production_id = self.env.context.get("parent_production_id")
        if (
            parent_production_id
        ):  # In this case, assign the newly created BoM to the MO.
            # Clean context to avoid parasitic default values.
            env = self.env(context=clean_context(self.env.context))
            production = env["mrp.production"].browse(parent_production_id)
            production._link_bom(res[0])
        return res

    def write(self, vals):
        res = super().write(vals)
        relevant_fields = [
            "bom_line_ids",
            "byproduct_ids",
            "product_tmpl_id",
            "product_id",
            "product_qty",
        ]
        if any(field_name in vals for field_name in relevant_fields):
            self._set_outdated_bom_in_productions()
        if "sequence" in vals and self and self[-1].id == list(self._prefetch_ids)[-1]:
            self.browse(self._prefetch_ids)._check_bom_cycle()
        return res

    def copy(self, default=None):
        new_boms = super().copy(default)
        for old_bom, new_bom in zip(self, new_boms, strict=True):
            if old_bom.operation_ids:
                operations_mapping = dict(
                    zip(
                        old_bom.operation_ids,
                        new_bom.operation_ids.sorted(),
                        strict=True,
                    )
                )
                for bom_line in new_bom.bom_line_ids:
                    if bom_line.operation_id:
                        bom_line.operation_id = operations_mapping[
                            bom_line.operation_id
                        ]
                for byproduct in new_bom.byproduct_ids:
                    if byproduct.operation_id:
                        byproduct.operation_id = operations_mapping[
                            byproduct.operation_id
                        ]
                for operation in old_bom.operation_ids:
                    if operation.blocked_by_operation_ids:
                        copied_operation = operations_mapping[operation]
                        dependencies = [
                            Command.link(operations_mapping[dependency].id)
                            for dependency in operation.blocked_by_operation_ids
                        ]
                        copied_operation.blocked_by_operation_ids = dependencies
        return new_boms

    @api.model
    def name_create(self, name):
        # prevent to use string as product_tmpl_id
        if isinstance(name, str):
            key = "default_" + self._rec_name
            if key in self.env.context:
                result = super().name_create(self.env.context[key])
                self.browse(result[0]).code = name
                return result
            raise UserError(_("You cannot create a new Bill of Material from here."))
        return super().name_create(name)

    def action_archive(self):
        self.with_context(active_test=False).operation_ids.action_archive()
        return super().action_archive()

    def action_unarchive(self):
        self.with_context(active_test=False).operation_ids.action_unarchive()
        return super().action_unarchive()

    @api.depends("code")
    def _compute_display_name(self):
        for bom in self:
            display_name = f"{bom.code + ': ' if bom.code else ''}{bom.product_tmpl_id.display_name}"
            if self.env.context.get("display_bom_uom_qty") and (
                bom.product_qty > 1 or bom.product_uom_id != bom.product_tmpl_id.uom_id
            ):
                display_name += f" ({bom.product_qty} {bom.product_uom_id.name})"
            # Not wrapped in `_()`: the msgid would be a bare placeholder, which
            # gives translators nothing to translate and exports a useless entry.
            bom.display_name = display_name

    @api.depends("operation_ids")
    def _compute_operation_count(self):
        for bom in self:
            bom.operation_count = len(bom.operation_ids)

    def _compute_show_copy_operations_button(self):
        exist_operation = bool(
            self.env["mrp.routing.workcenter"].search_count([], limit=1)
        )
        self.show_copy_operations_button = exist_operation

    def action_compute_bom_days(self):
        company_id = self.env.context.get("default_company_id", self.env.company.id)
        warehouse = self.env["stock.warehouse"].search(
            [("company_id", "=", company_id)], limit=1
        )
        for bom in self:
            bom_data = (
                self.env["report.mrp.report_bom_structure"]
                .with_context(minimized=True)
                ._get_bom_data(bom, warehouse, bom.product_id, ignore_stock=True)
            )
            bom.days_to_prepare_mo = self.env[
                "report.mrp.report_bom_structure"
            ]._get_max_component_delay(bom_data["components"])
            if bom_data.get("availability_state") == "unavailable" and not bom_data.get(
                "components_available", True
            ):
                return {
                    "type": "ir.actions.client",
                    "tag": "display_notification",
                    "params": {
                        "title": _(
                            "Cannot compute days to prepare due to missing route info for at least 1 component or for the final product."
                        ),
                        "sticky": False,
                    },
                }
        return None

    @api.constrains("product_tmpl_id", "product_id", "type")
    def check_kit_has_not_orderpoint(self):
        product_ids = [
            pid
            for bom in self.filtered(lambda bom: bom.type == "phantom")
            for pid in (
                bom.product_id.ids or bom.product_tmpl_id.product_variant_ids.ids
            )
        ]
        if self.env["stock.warehouse.orderpoint"].search_count(
            [("product_id", "in", product_ids)], limit=1
        ):
            raise ValidationError(
                _(
                    "You can not create a kit-type bill of materials for products that have at least one reordering rule."
                )
            )

    @api.constrains("enable_batch_size", "batch_size")
    def _check_valid_batch_size(self):
        if any(
            bom.enable_batch_size
            and bom.product_uom_id.compare(bom.batch_size, 0.0) <= 0
            for bom in self
        ):
            raise ValidationError(self.env._("The batch size must be positive!"))

    @api.ondelete(at_uninstall=False)
    def _unlink_except_running_mo(self):
        if self.env["mrp.production"].search_count(
            [("bom_id", "in", self.ids), ("state", "not in", ["done", "cancel"])],
            limit=1,
        ):
            raise UserError(
                _(
                    "You can not delete a Bill of Material with running manufacturing orders.\nPlease close or cancel it first."
                )
            )

    @api.model
    def _bom_find_domain(
        self, products, picking_type=None, company_id=False, bom_type=False
    ):
        domain = (
            Domain("product_id", "in", products.ids)
            | (
                Domain("product_id", "=", False)
                & Domain("product_tmpl_id", "in", products.product_tmpl_id.ids)
            )
        ) & Domain("active", "=", True)
        if company_id or self.env.context.get("company_id"):
            domain &= Domain(
                "company_id",
                "in",
                [False, company_id or self.env.context.get("company_id")],
            )
        if picking_type:
            domain &= Domain("picking_type_id", "in", [picking_type.id, False])
        if bom_type:
            domain &= Domain("type", "=", bom_type)
        return domain

    @api.model
    def _bom_find(self, products, picking_type=None, company_id=False, bom_type=False):
        """Find the first BoM for each products

        :param products: `product.product` recordset
        :return: One bom (or empty recordset `mrp.bom` if none find) by product (`product.product` record)
        :rtype: defaultdict(`lambda: self.env['mrp.bom']`)
        """
        bom_by_product = defaultdict(lambda: self.env["mrp.bom"])
        products = products.filtered(lambda p: p.type != "service")
        if not products:
            return bom_by_product
        domain = self._bom_find_domain(
            products,
            picking_type=picking_type,
            company_id=company_id,
            bom_type=bom_type,
        )

        # Performance optimization, allow usage of limit and avoid the for loop `bom.product_tmpl_id.product_variant_ids`
        if len(products) == 1:
            bom = self.search(domain, order="sequence, product_id, id", limit=1)
            if bom:
                bom_by_product[products] = bom
            return bom_by_product

        boms = self.search(domain, order="sequence, product_id, id")

        bom_by_product_tmpl = defaultdict(lambda: self.env["mrp.bom"])
        for bom in boms:
            if (
                bom.product_id
                and (bom.product_id.product_tmpl_id not in bom_by_product_tmpl)
                and (bom.product_id not in bom_by_product)
            ):
                bom_by_product[bom.product_id] = bom
            elif not bom.product_id and bom.product_tmpl_id not in bom_by_product_tmpl:
                bom_by_product_tmpl[bom.product_tmpl_id] = bom

        for product in products:
            if (
                product.product_tmpl_id in bom_by_product_tmpl
                and product not in bom_by_product
            ):
                bom_by_product[product] = bom_by_product_tmpl[product.product_tmpl_id]

        return bom_by_product

    def explode(
        self, product, quantity, picking_type=False, never_attribute_values=False
    ):
        """Explode the BoM, expanding phantom (kit) sub-BoMs recursively.

        :param quantity: the number of times the BoM is needed, i.e. the quantity
            divided by the number the BoM creates and converted into its UoM
        :return: (boms_done, lines_done), each a list of (record, values) tuples
        :rtype: tuple(list, list)
        """
        self = self.with_context(
            bom_cost_share_cache=self.env.context.get("bom_cost_share_cache") or {}
        )
        product_ids = set()
        product_boms = {}

        def update_product_boms():
            products = self.env["product.product"].browse(product_ids)
            product_boms.update(
                self._bom_find(
                    products,
                    picking_type=picking_type or self.picking_type_id,
                    company_id=self.company_id.id,
                    bom_type="phantom",
                )
            )
            # Set missing keys to default value
            for prod in products:
                product_boms.setdefault(prod, self.env["mrp.bom"])

        boms_done = [
            (
                self,
                self.env["mrp.bom.line"]._prepare_bom_done_values(
                    quantity, product, quantity, []
                ),
            )
        ]
        lines_done = []

        bom_lines = []
        for bom_line in self.bom_line_ids:
            product_id = bom_line.product_id
            # The 5th tuple element is the runtime cycle guard: the products whose phantom
            # BoM was already expanded on the path to this line (seeded with the finished
            # product). _check_bom_cycle resolves BoMs without the phantom/company/
            # picking_type parameters explode() uses, so a phantom-only cycle slips past
            # it and would loop here forever.
            bom_lines.append(
                (bom_line, product, quantity, False, frozenset((product.id,)))
            )
            product_ids.add(product_id.id)
        update_product_boms()
        product_ids.clear()
        while bom_lines:
            current_line, current_product, current_qty, parent_line, ancestors = (
                bom_lines[0]
            )
            bom_lines = bom_lines[1:]

            if current_line._skip_bom_line(current_product, never_attribute_values):
                continue

            line_quantity = current_qty * current_line.product_qty
            if current_line.product_id not in product_boms:
                update_product_boms()
                product_ids.clear()
            bom = product_boms.get(current_line.product_id)
            if bom:
                if current_line.product_id.id in ancestors:
                    raise ValidationError(
                        _(
                            "The current configuration is incorrect because it would "
                            "create a cycle between these products: %s.",
                            current_line.product_id.display_name,
                        )
                    )
                child_ancestors = ancestors | {current_line.product_id.id}
                converted_line_quantity = current_line.product_uom_id._compute_quantity(
                    line_quantity / bom.product_qty, bom.product_uom_id, round=False
                )
                bom_lines = [
                    (
                        line,
                        current_line.product_id,
                        converted_line_quantity,
                        current_line,
                        child_ancestors,
                    )
                    for line in bom.bom_line_ids
                ] + bom_lines
                for bom_line in bom.bom_line_ids:
                    if bom_line.product_id not in product_boms:
                        product_ids.add(bom_line.product_id.id)
                boms_done.append(
                    (
                        bom,
                        current_line._prepare_bom_done_values(
                            converted_line_quantity,
                            current_product,
                            quantity,
                            boms_done,
                        ),
                    )
                )
            else:
                # We round up here because the user expects that if he has to consume a little more, the whole UOM unit
                # should be consumed.
                line_quantity = current_line.product_uom_id.round(
                    line_quantity, rounding_method="UP"
                )
                lines_done.append(
                    (
                        current_line,
                        current_line._prepare_line_done_values(
                            line_quantity,
                            current_product,
                            quantity,
                            parent_line,
                            boms_done,
                        ),
                    )
                )

        lines_done = self._round_last_line_done(lines_done)
        return boms_done, lines_done

    @api.model
    def _round_last_line_done(self, lines_done):
        return lines_done

    @api.model
    def get_import_templates(self):
        return [
            {
                "label": _("Import Template for Bills of Materials"),
                "template": "/mrp/static/xls/mrp_bom.xls",
            }
        ]

    def _set_outdated_bom_in_productions(self):
        if not self:
            return
        # Searches for MOs using these BoMs to notify them that their BoM has been updated.
        list_of_domain_by_bom = []
        list_of_domain_by_bom_to_unmark = []
        for bom in self:
            if bom.product_id:
                domain_by_products = Domain("product_id", "=", bom.product_id.id)
            else:
                domain_by_products = Domain(
                    "product_id", "in", bom.product_tmpl_id.product_variant_ids.ids
                )
            domain_for_confirmed_mo = (
                Domain("state", "=", "confirmed") & domain_by_products
            )
            # Avoid confirmed MOs if the BoM's product was changed.
            domain_by_states = Domain("state", "=", "draft") | domain_for_confirmed_mo
            list_of_domain_by_bom.append(
                Domain("bom_id", "=", bom.id) & domain_by_states
            )
        productions = self.env["mrp.production"].search(
            Domain.OR(list_of_domain_by_bom)
        )
        if productions:
            productions.is_outdated_bom = True
        # Manually sets the MO's bom to not outdated if product or its variant is changed.
        if not self.env.context.get("skip_bom_outdated_unmark"):
            for bom in self:
                template_domain = [
                    ("state", "=", "confirmed"),
                    ("is_outdated_bom", "=", True),
                    ("bom_id", "=", bom.id),
                ]
                if bom.product_id:
                    template_domain.append(("product_id", "!=", bom.product_id.id))
                else:
                    template_domain.append(
                        ("product_tmpl_id", "!=", bom.product_tmpl_id.id)
                    )
                list_of_domain_by_bom_to_unmark.append(template_domain)
            if list_of_domain_by_bom_to_unmark:
                self.env["mrp.production"].search(
                    Domain.OR(list_of_domain_by_bom_to_unmark)
                ).write({"is_outdated_bom": False})

    # -------------------------------------------------------------------------
    # CATALOG
    # -------------------------------------------------------------------------

    def _get_action_add_from_catalog_extra_context(self):
        return {
            **super()._get_action_add_from_catalog_extra_context(),
            "product_catalog_currency_id": self.env.company.currency_id.id,
        }

    def _default_order_line_values(self, child_field=False):
        default_data = super()._default_order_line_values(child_field)
        new_default_data = self[child_field]._get_product_catalog_lines_data(
            default=True
        )

        return {**default_data, **new_default_data}

    def _get_product_catalog_order_data(self, products, **kwargs):
        product_catalog = super()._get_product_catalog_order_data(products, **kwargs)
        for product in products:
            product_catalog[product.id] |= self._get_product_price_and_data(product)
        return product_catalog

    def _get_product_price_and_data(self, product):
        self.ensure_one()
        return {"price": product.standard_price}

    def _get_product_catalog_record_lines(
        self, product_ids, *, child_field=False, **kwargs
    ):
        if not child_field:
            return {}
        lines = self[child_field].filtered(
            lambda line: line.product_id.id in product_ids
        )
        return lines.grouped("product_id")

    def _update_order_line_info(
        self, product_id, quantity, *, child_field=False, **kwargs
    ):
        if not child_field:
            return 0
        entity = self[child_field].filtered(
            lambda line: line.product_id.id == product_id
        )
        if entity:
            if quantity != 0:
                entity.product_qty = quantity
            else:
                entity.unlink()
        elif quantity > 0:
            command = Command.create(
                {
                    "product_qty": quantity,
                    "product_id": product_id,
                }
            )
            self.write({child_field: [command]})

        return self.env["product.product"].browse(product_id).standard_price

    # -------------------------------------------------------------------------
    # DOCUMENT
    # -------------------------------------------------------------------------

    def _get_mail_thread_data_attachments(self):
        res = super()._get_mail_thread_data_attachments()
        for bom in self:
            res[bom.id] |= bom._get_extra_attachments()
        return res

    def _get_extra_attachments(self):
        is_byproduct = self.env.user.has_group("mrp.group_mrp_byproducts")
        product_ids, template_ids = OrderedSet(), OrderedSet()
        for bom in self:
            product_ids.add(bom.product_id.id)
            template_ids.add(bom.product_tmpl_id.id)
            if is_byproduct:
                product_ids.update(bom.byproduct_ids.product_id.ids)
                template_ids.update(bom.byproduct_ids.product_id.product_tmpl_id.ids)

        domain = Domain("attached_on_mrp", "=", "bom") & (
            (
                Domain("res_model", "=", "product.product")
                & Domain("res_id", "in", product_ids)
            )
            | (
                Domain("res_model", "=", "product.template")
                & Domain("res_id", "in", template_ids)
            )
        )
        return self.env["product.document"].search(domain).ir_attachment_id

    @api.model
    def _skip_for_no_variant(
        self, product, bom_attribule_values, never_attribute_values=False
    ):
        """Controls if a Component/Operation/Byproduct line should be skipped based on
        the 'no_variant' attributes.

        A 'no_variant' attribute on the line needs at least one value in common with
        `never_attribute_values`; 'always' and 'dynamic' ones go through
        `product._match_all_variant_values`. The branches below take the cases in turn.
        """
        no_variant_bom_attributes = bom_attribule_values.filtered(
            lambda av: av.attribute_id.create_variant == "no_variant"
        )

        # Attributes create_variant 'always' and 'dynamic'
        other_attribute_valid = product._match_all_variant_values(
            bom_attribule_values - no_variant_bom_attributes
        )

        # If there are no never attribute values on the line => 'always' and 'dynamic'
        if not no_variant_bom_attributes:
            return not other_attribute_valid

        # Or if the line has no_variant attributes but no value is passed => cannot match
        if not never_attribute_values:
            return True

        bom_values_by_attribute = no_variant_bom_attributes.grouped("attribute_id")
        never_values_by_attribute = never_attribute_values.grouped("attribute_id")

        # Or if there is no overlap between the given values' attributes and the BoM's
        if not any(
            never_att_id in no_variant_bom_attributes.attribute_id.ids
            for never_att_id in never_attribute_values.attribute_id.ids
        ):
            return True

        # Check that at least one variant attribute is correct
        for attribute, values in bom_values_by_attribute.items():
            if never_values_by_attribute.get(attribute) and any(
                val.id in never_values_by_attribute[attribute].ids for val in values
            ):
                return not other_attribute_valid

        # None were found, so we skip the line
        return True

    # -------------------------------------------------------------------------
    # REPLENISHMENT WIZARD
    # -------------------------------------------------------------------------

    def _compute_show_set_bom_button(self):
        self.show_set_bom_button = True
        orderpoint_id = self.env.context.get(
            "orderpoint_id", self.env.context.get("default_orderpoint_id")
        )
        if orderpoint_id:
            orderpoint = self.env["stock.warehouse.orderpoint"].browse(orderpoint_id)
            self.filtered(
                lambda s: s.id == orderpoint.bom_id.id
            ).show_set_bom_button = False

    def action_set_bom_on_orderpoint(self):
        self.ensure_one()
        orderpoint_id = self.env.context.get("orderpoint_id")
        if not orderpoint_id:
            return None
        orderpoint = self.env["stock.warehouse.orderpoint"].browse(orderpoint_id)
        if "manufacture" not in orderpoint.route_id.rule_ids.mapped("action"):
            domain = Domain.AND(
                [
                    [("action", "=", "manufacture")],
                    Domain.OR(
                        [
                            [("company_id", "=", orderpoint.company_id.id)],
                            [("company_id", "=", False)],
                        ]
                    ),
                ]
            )
            orderpoint.route_id = (
                self.env["stock.rule"].search(domain, limit=1).route_id.id
            )
        orderpoint.bom_id = self
        bom_qty = self.product_uom_id._compute_quantity(
            self.product_qty, orderpoint.product_id.uom_id
        )
        orderpoint.qty_to_order = max(orderpoint.qty_to_order, bom_qty)
        return orderpoint.action_stock_replenishment_info()

    def action_open_operation_form(self):
        self.ensure_one()
        return {
            "type": "ir.actions.act_window",
            "view_mode": "form",
            "res_model": "mrp.routing.workcenter",
            "context": {
                "default_bom_id": self.id,
                "search_default_bom_id": self.id,
                "bom_id_invisible": True,
            },
        }

    def action_copy_existing_operations(self):
        self.ensure_one()
        return (
            self.env["mrp.routing.workcenter"]
            .with_context(bom_id=self.id)
            .copy_existing_operations()
        )


class MrpBomLine(models.Model):
    _name = "mrp.bom.line"
    _order = "sequence, id"
    _rec_name = "product_id"
    _description = "Bill of Material Line"
    _check_company_auto = True

    def _get_default_product_uom_id(self):
        return self.env["uom.uom"].search([], limit=1, order="id").id

    product_id = fields.Many2one(
        "product.product", "Component", required=True, check_company=True, index=True
    )
    product_tmpl_id = fields.Many2one(
        "product.template",
        "Product Template",
        related="product_id.product_tmpl_id",
        store=True,
        index=True,
    )
    company_id = fields.Many2one(
        related="bom_id.company_id", store=True, index=True, readonly=True
    )
    product_qty = fields.Float(
        "Quantity", default=1.0, digits="Product Unit", required=True
    )
    product_uom_id = fields.Many2one(
        "uom.uom", "Unit", default=_get_default_product_uom_id, required=True
    )
    sequence = fields.Integer(
        "Sequence", default=1, help="Gives the sequence order when displaying."
    )
    bom_id = fields.Many2one(
        "mrp.bom", "Parent BoM", index=True, ondelete="cascade", required=True
    )
    parent_product_tmpl_id = fields.Many2one(
        "product.template", "Parent Product Template", related="bom_id.product_tmpl_id"
    )
    possible_bom_product_template_attribute_value_ids = fields.Many2many(
        related="bom_id.possible_product_template_attribute_value_ids"
    )
    bom_product_template_attribute_value_ids = fields.Many2many(
        "product.template.attribute.value",
        string="Apply on Variants",
        ondelete="restrict",
        domain="[('id', 'in', possible_bom_product_template_attribute_value_ids)]",
        help="BOM Product Variants needed to apply this line.",
    )
    allowed_operation_ids = fields.One2many(
        "mrp.routing.workcenter", related="bom_id.operation_ids"
    )
    operation_id = fields.Many2one(
        "mrp.routing.workcenter",
        "Consumed in Operation",
        check_company=True,
        domain="[('id', 'in', allowed_operation_ids)]",
        help="The operation where the components are consumed, or the finished products created.",
    )
    child_bom_id = fields.Many2one(
        "mrp.bom", "Sub BoM", compute="_compute_child_bom_id"
    )
    child_line_ids = fields.One2many(
        "mrp.bom.line",
        string="BOM lines of the referred bom",
        compute="_compute_child_line_ids",
    )
    attachments_count = fields.Integer(
        "Attachments Count", compute="_compute_attachments_count"
    )
    tracking = fields.Selection(related="product_id.tracking")

    _bom_qty_zero = models.Constraint(
        "CHECK (product_qty>=0)",
        "All product quantities must be greater or equal to 0.\nLines with 0 quantities can be used as optional lines. \nYou should install the mrp_byproduct module if you want to manage extra products on BoMs!",
    )

    @api.depends("product_id", "bom_id")
    def _compute_child_bom_id(self):
        products = self.product_id
        bom_by_product = self.env["mrp.bom"]._bom_find(products)
        for line in self:
            if not line.product_id:
                line.child_bom_id = False
            else:
                line.child_bom_id = bom_by_product.get(line.product_id, False)

    @api.depends("product_id")
    def _compute_attachments_count(self):
        # Two grouped queries for the whole set. This ran one `search_count` per
        # line, and every component row of every BoM form reads it.
        counts_by_product = {}
        counts_by_template = {}
        for res_model, counts in (
            ("product.product", counts_by_product),
            ("product.template", counts_by_template),
        ):
            res_ids = (
                self.product_id.ids
                if res_model == "product.product"
                else self.product_tmpl_id.ids
            )
            if not res_ids:
                continue
            counts.update(
                dict(
                    self.env["product.document"]._read_group(
                        [
                            ("attached_on_mrp", "=", "bom"),
                            ("active", "=", True),
                            ("res_model", "=", res_model),
                            ("res_id", "in", res_ids),
                        ],
                        ["res_id"],
                        ["__count"],
                    )
                )
            )
        for line in self:
            line.attachments_count = counts_by_product.get(
                line.product_id.id, 0
            ) + counts_by_template.get(line.product_tmpl_id.id, 0)

    @api.depends("child_bom_id")
    def _compute_child_line_ids(self):
        """Set the child BoM's lines on the line, when it refers to a BoM."""
        for line in self:
            line.child_line_ids = line.child_bom_id.bom_line_ids.ids or False

    @api.constrains("product_uom_id", "product_id")
    def _check_product_uom_id_category(self):
        """A component line must be quantified in a unit measuring its component.

        Same reasoning as `mrp.bom._check_product_uom_id_category`: `create`
        and the onchange below align the unit only when it is not supplied, so
        an explicit cross-category value reached `explode()` and the cost
        roll-up unchecked.
        """
        for line in self:
            component_uom = line.product_id.uom_id
            if (
                line.product_uom_id
                and component_uom
                and not line.product_uom_id._has_common_reference(component_uom)
            ):
                raise ValidationError(
                    _(
                        "The component %(product)s is used in %(unit)s, which does"
                        " not measure the same thing as its own unit"
                        " %(product_unit)s.",
                        product=line.product_id.display_name,
                        unit=line.product_uom_id.display_name,
                        product_unit=component_uom.display_name,
                    )
                )

    @api.onchange("product_id")
    def onchange_product_id(self):
        if self.product_id:
            self.product_uom_id = self.product_id.uom_id.id

    @api.model_create_multi
    def create(self, vals_list):
        for values in vals_list:
            if "product_id" in values and "product_uom_id" not in values:
                values["product_uom_id"] = (
                    self.env["product.product"].browse(values["product_id"]).uom_id.id
                )
        return super().create(vals_list)

    # Component changes worth an entry in the parent BoM chatter. `sequence` is
    # deliberately out: reordering the components rewrites it on every line at once
    # and would bury the real edits. So are the stored related fields
    # (`product_tmpl_id`, `company_id`), which the ORM rewrites by itself.
    CHATTER_TRACKED_FIELDS = (
        "product_id",
        "product_qty",
        "product_uom_id",
        "operation_id",
        "bom_product_template_attribute_value_ids",
    )

    def write(self, vals):
        tracked = [name for name in self.CHATTER_TRACKED_FIELDS if name in vals]
        if not tracked or self._chatter_is_muted():
            return super().write(vals)

        # Snapshot before the write, since the whole point is the old value. The
        # component name is captured apart from the tracked values: it heads the
        # chatter entry even when `product_id` itself is what changed.
        before = {
            line.id: (line.product_id.display_name, line._get_chatter_values(tracked))
            for line in self
        }
        result = super().write(vals)

        changes_by_bom = defaultdict(list)
        for line in self:
            component, old_values = before[line.id]
            new_values = line._get_chatter_values(tracked)
            changes = [
                (line._get_chatter_label(name), old_values[name], new_values[name])
                for name in tracked
                if old_values[name] != new_values[name]
            ]
            if changes:
                changes_by_bom[line.bom_id].append((component, changes))

        for bom, entries in changes_by_bom.items():
            bom.message_post(
                body=Markup("{}<ul>{}</ul>").format(
                    self.env._("Components updated:"),
                    Markup("").join(
                        Markup("<li><b>{}</b><ul>{}</ul></li>").format(
                            component,
                            Markup("").join(
                                starmap(Markup("<li>{}: {} → {}</li>").format, changes)
                            ),
                        )
                        for component, changes in entries
                    ),
                ),
                subtype_xmlid="mail.mt_note",
            )
        return result

    def unlink(self):
        # Deleting a whole BoM cascades through `bom_id`'s `ondelete` in SQL, so it
        # never reaches this override and never posts to a thread on its way out.
        if self._chatter_is_muted():
            return super().unlink()

        for bom, lines in self.grouped("bom_id").items():
            bom.message_post(
                body=Markup("{}<ul>{}</ul>").format(
                    self.env._("Components removed:"),
                    Markup("").join(
                        Markup("<li><b>{}</b> — {}: {} {}</li>").format(
                            line.product_id.display_name,
                            line._get_chatter_label("product_qty"),
                            formatLang(self.env, line.product_qty, dp="Product Unit"),
                            line.product_uom_id.display_name,
                        )
                        for line in lines
                    ),
                ),
                subtype_xmlid="mail.mt_note",
            )
        return super().unlink()

    def _chatter_is_muted(self):
        """Whether this write should stay out of the parent BoM's chatter.

        An entry that mimics field tracking has no business ignoring the switches
        `mail.thread` itself obeys (`mail_thread.py:498`): module loading, imports
        and `copy_data` already set them, and so does any bulk restamp that is not
        a user editing a component -- `product.product._update_uom` being the one
        in `mrp`, which would otherwise post to every BoM holding the product.
        """
        return bool(
            self.env.context.get("tracking_disable")
            or self.env.context.get("mail_notrack")
        )

    def _get_chatter_label(self, field_name):
        """Translated label of a field, as the chatter entry should name it."""
        return self._fields[field_name].get_description(
            self.env, attributes=["string"]
        )["string"]

    def _get_chatter_values(self, field_names):
        """Readable value of `field_names`, keyed by name, for one component line."""
        self.ensure_one()
        return {name: self._get_chatter_value(name) for name in field_names}

    def _get_chatter_value(self, field_name):
        """Render one field the way the chatter should show it, old or new."""
        self.ensure_one()
        field = self._fields[field_name]
        value = self[field_name]
        if field.relational:
            return ", ".join(value.mapped("display_name")) or self.env._("(none)")
        if field.type == "float":
            # `product_qty` is the only tracked float, and it carries the "Product
            # Unit" precision -- printing it raw would show its full binary tail.
            return formatLang(self.env, value, dp="Product Unit")
        if field.type == "selection":
            return dict(field._description_selection(self.env)).get(value, value)
        return str(value)

    def _skip_bom_line(self, product, never_attribute_values=False):
        """Control if a BoM line should be produced, can be inherited to add custom control.

        The attribute matching rules live in `mrp.bom._skip_for_no_variant`.
        """
        self.ensure_one()
        if not product or product._name == "product.template":
            return False

        return self.env["mrp.bom"]._skip_for_no_variant(
            product,
            self.bom_product_template_attribute_value_ids,
            never_attribute_values,
        )

    def action_see_attachments(self):
        domain = [
            "&",
            ("attached_on_mrp", "=", "bom"),
            "|",
            "&",
            ("res_model", "=", "product.product"),
            ("res_id", "=", self.product_id.id),
            "&",
            ("res_model", "=", "product.template"),
            ("res_id", "=", self.product_id.product_tmpl_id.id),
        ]
        attachments = self.env["product.document"].search(domain)
        nbr_product_attach = len(
            attachments.filtered(lambda a: a.res_model == "product.product")
        )
        nbr_template_attach = len(
            attachments.filtered(lambda a: a.res_model == "product.template")
        )
        context = {
            "default_res_model": "product.product",
            "default_res_id": self.product_id.id,
            "default_company_id": self.company_id.id,
            "attached_on_bom": True,
            "search_default_context_variant": not (
                nbr_product_attach == 0 and nbr_template_attach > 0
            )
            if self.env.user.has_group("product.group_product_variant")
            else False,
        }

        return {
            "name": _("Attachments"),
            "domain": domain,
            "res_model": "product.document",
            "type": "ir.actions.act_window",
            "view_mode": "kanban,list,form",
            "target": "current",
            "help": _("""<p class="o_view_nocontent_smiling_face">
                        Upload files to your product
                    </p><p>
                        Use this feature to store any files, like drawings or specifications.
                    </p>"""),
            "limit": 80,
            "context": context,
            "search_view_id": self.env.ref("product.view_product_document_search").ids,
        }

    # -------------------------------------------------------------------------
    # CATALOG
    # -------------------------------------------------------------------------

    def action_add_from_catalog(self):
        bom = self.env["mrp.bom"].browse(self.env.context.get("order_id"))
        return bom.with_context(child_field="bom_line_ids").action_add_from_catalog()

    def _get_product_catalog_lines_data(self, default=False, **kwargs):
        if self and not default:
            self.product_id.ensure_one()
            return {
                **self[0].bom_id._get_product_price_and_data(self[0].product_id),
                "quantity": sum(
                    self.mapped(
                        lambda line: line.product_uom_id._compute_quantity_report(
                            qty=line.product_qty,
                            to_unit=line.product_uom_id,
                        )
                    )
                ),
                "readOnly": len(self) > 1,
                "uomDisplayName": (len(self) == 1 and self.product_uom_id.display_name)
                or self.product_id.uom_id.display_name,
            }
        return {
            "quantity": 0,
        }

    def _prepare_bom_done_values(self, quantity, product, original_quantity, boms_done):
        return {
            "qty": quantity,
            "product": product,
            "original_qty": original_quantity,
            "parent_line": self,
        }

    def _prepare_line_done_values(
        self, quantity, product, original_quantity, parent_line, boms_done
    ):
        return {
            "qty": quantity,
            "product": product,
            "original_qty": original_quantity,
            "parent_line": parent_line,
        }


class MrpBomByproduct(models.Model):
    _name = "mrp.bom.byproduct"
    _description = "Byproduct"
    _rec_name = "product_id"
    _check_company_auto = True
    _order = "sequence, id"

    product_id = fields.Many2one(
        "product.product", "By-product", required=True, check_company=True
    )
    company_id = fields.Many2one(
        related="bom_id.company_id", store=True, index=True, readonly=True
    )
    product_qty = fields.Float(
        "Quantity", default=1.0, digits="Product Unit", required=True
    )
    product_uom_id = fields.Many2one(
        "uom.uom",
        "Unit",
        required=True,
        compute="_compute_product_uom_id",
        store=True,
        readonly=False,
        precompute=True,
    )
    bom_id = fields.Many2one("mrp.bom", "BoM", ondelete="cascade", index=True)
    allowed_operation_ids = fields.One2many(
        "mrp.routing.workcenter", related="bom_id.operation_ids"
    )
    operation_id = fields.Many2one(
        "mrp.routing.workcenter",
        "Produced in Operation",
        check_company=True,
        domain="[('id', 'in', allowed_operation_ids)]",
    )
    possible_bom_product_template_attribute_value_ids = fields.Many2many(
        related="bom_id.possible_product_template_attribute_value_ids"
    )
    bom_product_template_attribute_value_ids = fields.Many2many(
        "product.template.attribute.value",
        string="Apply on Variants",
        ondelete="restrict",
        domain="[('id', 'in', possible_bom_product_template_attribute_value_ids)]",
        help="BOM Product Variants needed to apply this line.",
    )
    sequence = fields.Integer("Sequence")
    cost_share = fields.Float(
        "Cost Share (%)",
        digits=(5, 2),  # decimal = 2 is important for rounding calculations!!
        help="The percentage of the final production cost for this by-product line (divided between the quantity produced)."
        "The total of all by-products' cost share must be less than or equal to 100.",
    )

    @api.constrains("product_uom_id", "product_id")
    def _check_product_uom_id_category(self):
        """A by-product must be quantified in a unit measuring it.

        The compute below is `readonly=False`, so a value written explicitly
        survives and would otherwise feed `cost_share` allocation and the
        by-product moves in a unit unrelated to the product.
        """
        for byproduct in self:
            byproduct_uom = byproduct.product_id.uom_id
            if (
                byproduct.product_uom_id
                and byproduct_uom
                and not byproduct.product_uom_id._has_common_reference(byproduct_uom)
            ):
                raise ValidationError(
                    _(
                        "The by-product %(product)s is produced in %(unit)s, which"
                        " does not measure the same thing as its own unit"
                        " %(product_unit)s.",
                        product=byproduct.product_id.display_name,
                        unit=byproduct.product_uom_id.display_name,
                        product_unit=byproduct_uom.display_name,
                    )
                )

    @api.depends("product_id")
    def _compute_product_uom_id(self):
        """Changes UoM if product_id changes."""
        for record in self:
            record.product_uom_id = record.product_id.uom_id.id

    def _skip_byproduct_line(self, product, never_attribute_values=False):
        """Control if a byproduct line should be produced, can be inherited to add
        custom control.
        """
        self.ensure_one()
        if not product or product._name == "product.template":
            return False

        return self.env["mrp.bom"]._skip_for_no_variant(
            product,
            self.bom_product_template_attribute_value_ids,
            never_attribute_values,
        )

    # -------------------------------------------------------------------------
    # CATALOG
    # -------------------------------------------------------------------------

    def action_add_from_catalog(self):
        bom = self.env["mrp.bom"].browse(self.env.context.get("order_id"))
        return bom.with_context(child_field="byproduct_ids").action_add_from_catalog()

    def _get_product_catalog_lines_data(self, default=False, **kwargs):
        if self and not default:
            self.product_id.ensure_one()
            return {
                **self[0].bom_id._get_product_price_and_data(self[0].product_id),
                "quantity": sum(
                    self.mapped(
                        lambda line: line.product_uom_id._compute_quantity_report(
                            qty=line.product_qty,
                            to_unit=line.product_uom_id,
                        )
                    )
                ),
                "readOnly": len(self) > 1,
                "uomDisplayName": (len(self) == 1 and self.product_uom_id.display_name)
                or self.product_id.uom_id.display_name,
            }
        return {
            "quantity": 0,
        }
