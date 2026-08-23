from collections import defaultdict, deque

from odoo import _, api, fields, models
from odoo.exceptions import UserError, ValidationError
from odoo.fields import Command, Domain
from odoo.tools import float_compare
from odoo.tools.misc import OrderedSet, clean_context


class ExplodeScratch(dict):
    """A cache carried on the context for the length of one ``explode()``.

    A plain ``dict`` in a context is hashed **in full** every time an
    ``Environment`` is built from it: ``frozendict.__hash__`` calls ``freehash``
    on each value, ``hash(dict)`` raises, and the fallback rebuilds a frozendict
    of the whole mapping, uncached. The cost is linear in the cache, which grows
    as the explosion walks -- measured 1.18 us to hash the context without it,
    66.85 us with 600 entries in it.

    Hashing by identity also keeps the hash contract that a growing dict breaks:
    two contexts that compare equal must hash equal, and equality here is
    identity of the same scratch object.
    """

    __slots__ = ()
    __hash__ = object.__hash__
    __eq__ = object.__eq__
    __ne__ = object.__ne__


class MrpBom(models.Model):
    _name = "mrp.bom"
    _description = "Bill of Material"
    _inherit = [
        "mixin.mail.thread",
        # before `mixin.product.catalog`: its `_update_order_line_info` is a
        # `return 0` stub, and the first entry wins the method resolution order.
        "mixin.catalog.child.lines",
        "mixin.product.catalog",
    ]
    _rec_name = "product_tmpl_id"
    _rec_names_search = ["product_tmpl_id", "code"]
    _order = "sequence, id"
    _check_company_auto = True

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

    @api.constrains(
        "active", "product_id", "product_tmpl_id", "bom_line_ids", "sequence"
    )
    def _check_bom_cycle(self):
        # A BoM that is not the one `_bom_find` currently selects is still a BoM
        # the next reorder can select, so every BoM competing for a product the
        # walk reaches is checked as if it were the selected one. Which BoM wins
        # is decided by `sequence`, which is why `sequence` is in the constraint.
        #
        # This set used to be `self` plus the producers of `self`'s components,
        # widened in practice by `write()` re-checking `self._prefetch_ids`
        # whenever the last record of a prefetch set was written -- so what got
        # validated depended on how the caller happened to iterate. It is a
        # fixed point over the reachable closure instead.
        subcomponents_by_product = {}
        checked = self.browse()
        boms_to_check = self
        while boms_to_check:
            reached = self.env["product.product"]
            for bom in boms_to_check:
                if not bom.active:
                    continue
                reached |= bom.bom_line_ids.product_id
                for components, finished in bom._get_cycle_seeds():
                    self._check_no_cycle_from(
                        components, finished, subcomponents_by_product
                    )
                    reached |= components
            checked |= boms_to_check
            reached |= self.env["product.product"].browse(
                {
                    product.id
                    for components in subcomponents_by_product.values()
                    for product in components
                }
            )
            boms_to_check = (
                self.search(Domain.OR(self._bom_find_domain(p) for p in reached))
                - checked
                if reached
                else self.browse()
            )

    def _check_no_cycle_from(self, components, finished_products, subcomponents):
        """Raise if `components` can reach `finished_products` or loop.

        Depth-first with the ancestor path as the grey set and `visited` as the
        black set. Without the black set the walk enumerates every root-to-leaf
        *path*, which is exponential as soon as two parents share a component --
        an ordinary sub-assembly. Measured on a 38-product diamond: 2.7 s,
        quadrupling per extra level.

        `visited` MUST NOT outlive this call. It records "no cycle reaches this
        product under *this* seed", and `finished_products` is part of the seed:
        a product cleared while checking one BoM can still close a cycle onto
        another BoM's finished product. `subcomponents` is safe to share -- what
        a product is made of does not depend on where the walk started.
        """
        visited = set()

        def _walk(components, finished_products):
            self._add_missing_subcomponents(components, subcomponents)
            for component in components:
                if component in finished_products:
                    raise ValidationError(
                        _(
                            "The current configuration is incorrect because it would create a cycle between these products: %s.",
                            ", ".join(finished_products.mapped("display_name")),
                        )
                    )
            for component in components:
                if component.id in visited:
                    continue
                if subcomponents[component]:
                    _walk(subcomponents[component], finished_products | component)
                visited.add(component.id)

        _walk(components, finished_products)

    def _add_missing_subcomponents(self, products, subcomponents):
        """Add to *subcomponents* what each *products* entry it lacks is made of.

        One ``_bom_find`` for the whole unknown set, so a walk that revisits a
        product costs nothing: "missing" is what makes it safe to call on every
        step of the recursion.
        """
        unknown = products.filtered(lambda p: p not in subcomponents)
        if not unknown:
            return
        bom_by_product = self._bom_find(unknown)
        for product in unknown:
            subcomponents[product] = (
                bom_by_product[product]
                .bom_line_ids.filtered(
                    lambda line, product=product: not line._skip_bom_line(product)
                )
                .product_id
            )

    def _get_cycle_seeds(self):
        """`(components, finished_products)` pairs this BoM must be walked from.

        One pair, unless the lines are restricted to variants: then each distinct
        component set is walked once, against the variants it applies to.
        """
        self.ensure_one()
        finished_products = self.product_id or self.product_tmpl_id.product_variant_ids
        if not self.bom_line_ids.bom_product_template_attribute_value_ids:
            return [(self.bom_line_ids.product_id, finished_products)]
        grouped_by_components = defaultdict(lambda: self.env["product.product"])
        for finished in finished_products:
            components = self.bom_line_ids.filtered(
                lambda line, finished=finished: not line._skip_bom_line(finished)
            ).product_id
            grouped_by_components[components] |= finished
        return list(grouped_by_components.items())

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
                        _("By-products cost shares cannot be negative.")
                    )
            byproducts = bom.byproduct_ids.filtered(
                lambda bp: not bp.product_uom_id.is_zero(bp.product_qty)
            )
            if not byproducts:
                continue
            # The total only varies by variant when some by-product is restricted
            # to one, and a variant-specific BoM has a single variant to answer
            # for. Otherwise one representative settles it, instead of walking
            # every variant of the template for every by-product.
            variants = bom.product_id or bom.product_tmpl_id.product_variant_ids
            if not byproducts.bom_product_template_attribute_value_ids:
                variants = variants[:1]
            for product in variants:
                total_variant_cost_share = sum(
                    byproducts.filtered(
                        lambda bp, product=product: not bp._skip_bom_line(product)
                    ).mapped("cost_share")
                )
                if float_compare(total_variant_cost_share, 100, precision_digits=2) > 0:
                    raise ValidationError(
                        _(
                            "The total cost share for a BoM's by-products cannot exceed 100."
                        )
                    )

    @api.onchange("bom_line_ids", "product_qty", "product_id", "product_tmpl_id")
    def _onchange_bom_structure(self):
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
    def _onchange_product_tmpl_id(self):
        if self.product_tmpl_id:
            default_uom_id = self.env.context.get("default_product_uom_id")
            if self.product_uom_id.id != default_uom_id:
                self.product_uom_id = self.product_tmpl_id.uom_id.id
            if self.product_id.product_tmpl_id != self.product_tmpl_id:
                self.product_id = False
            warning = self._reset_variant_data()

            domain = [("product_tmpl_id", "=", self.product_tmpl_id.id)]
            if self.id.origin:
                domain.append(("id", "!=", self.id.origin))
            # Only ever fills an empty reference. This used to overwrite one the
            # user had already typed, and the count is of the BoMs that exist, so
            # the second BoM of a product is "(new) 1".
            if not self.code:
                number_of_bom_of_this_product = self.search_count(domain)
                if number_of_bom_of_this_product:
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
        # A BoM is quantified in its product's unit unless told otherwise. The
        # templates are read in one go, and `vals_list` is left as the caller
        # passed it -- this used to write `product_uom_id` into the caller's own
        # dicts, which a caller reusing one for several records then inherited.
        needs_uom = [
            values
            for values in vals_list
            if values.get("product_tmpl_id") and "product_uom_id" not in values
        ]
        if needs_uom:
            templates = self.env["product.template"].browse(
                {values["product_tmpl_id"] for values in needs_uom}
            )
            uom_by_template = {
                template.id: template.uom_id.id for template in templates
            }
            vals_list = [
                {**values, "product_uom_id": uom_by_template[values["product_tmpl_id"]]}
                if values in needs_uom
                else values
                for values in vals_list
            ]
        res = super().create(vals_list)
        parent_production_id = self.env.context.get("parent_production_id")
        if parent_production_id:
            env = self.env(context=clean_context(self.env.context))
            production = env["mrp.production"].browse(parent_production_id)
            for bom in res:
                production._link_bom(bom)
        return res

    _OUTDATING_FIELDS = (
        "bom_line_ids",
        "byproduct_ids",
        "product_tmpl_id",
        "product_id",
        "product_qty",
    )

    def write(self, vals):
        res = super().write(vals)
        if any(field_name in vals for field_name in self._OUTDATING_FIELDS):
            self._update_outdated_bom_in_productions()
        return res

    def copy(self, default=None):
        # The operations are copied here rather than by the one2many, because
        # the lines, the by-products and the dependency graph all have to be
        # re-pointed at them and that needs a mapping that cannot be wrong.
        # `copy()` resolves to `create([vals])`, which returns records in vals
        # order, so zipping a recordset with its own copy is exact -- the same
        # contract this method already relies on for the boms themselves.
        # Pairing by position in the two one2manys is not: `operation_ids` is
        # served in `_order` from the database but in insertion order from a
        # warm cache, and when those disagree the copy silently swaps every
        # line's operation and reverses `blocked_by_operation_ids`.
        new_boms = super().copy({**(default or {}), "operation_ids": []})
        for old_bom, new_bom in zip(self, new_boms, strict=True):
            operations = old_bom.operation_ids
            if not operations:
                continue
            copied_by_operation = dict(
                zip(operations, operations.copy({"bom_id": new_bom.id}), strict=True)
            )
            for lines in (new_bom.bom_line_ids, new_bom.byproduct_ids):
                for line in lines:
                    if line.operation_id:
                        line.operation_id = copied_by_operation[line.operation_id]
            for operation in operations:
                if operation.blocked_by_operation_ids:
                    copied_by_operation[operation].blocked_by_operation_ids = [
                        Command.link(copied_by_operation[dependency].id)
                        for dependency in operation.blocked_by_operation_ids
                    ]
        return new_boms

    @api.model
    def name_create(self, name):
        # A BoM has no name of its own: what the user types in a many2one is its
        # `code`, and the record it names is the one already in the context.
        product_tmpl_id = self.env.context.get("default_product_tmpl_id")
        if not product_tmpl_id:
            raise UserError(_("You cannot create a new Bill of Material from here."))
        bom = self.create({"product_tmpl_id": product_tmpl_id, "code": name})
        return bom.id, bom.display_name

    def action_archive(self):
        # Only the operations that are live right now follow the BoM down, and
        # they are stamped so that unarchiving brings back exactly those. The
        # inverse of "archive everything" is not "unarchive everything": an
        # operation retired on its own must stay retired.
        operations = self.operation_ids
        operations.archived_with_bom = True
        operations.action_archive()
        return super().action_archive()

    def action_unarchive(self):
        operations = self.with_context(active_test=False).operation_ids.filtered(
            "archived_with_bom"
        )
        operations.action_unarchive()
        operations.archived_with_bom = False
        return super().action_unarchive()

    @api.depends(
        "code", "product_tmpl_id.display_name", "product_qty", "product_uom_id"
    )
    @api.depends_context("display_bom_uom_qty")
    def _compute_display_name(self):
        for bom in self:
            display_name = f"{bom.code + ': ' if bom.code else ''}{bom.product_tmpl_id.display_name}"
            if self.env.context.get("display_bom_uom_qty") and (
                bom.product_qty > 1 or bom.product_uom_id != bom.product_tmpl_id.uom_id
            ):
                display_name += f" ({bom.product_qty} {bom.product_uom_id.name})"
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
        report = self.env["report.mrp.report_bom_structure"]
        incomplete = self.browse()
        for bom in self:
            bom_data = report.with_context(minimized=True)._get_bom_data(
                bom, warehouse, bom.product_id, ignore_stock=True
            )
            bom.days_to_prepare_mo = report._get_max_component_delay(
                bom_data["components"]
            )
            if bom_data.get("availability_state") == "unavailable" and not bom_data.get(
                "components_available", True
            ):
                incomplete |= bom
        # Every BoM is computed before reporting: returning from inside the loop
        # left the ones after the first incomplete BoM on their old value, and
        # named none of them.
        if not incomplete:
            return None
        return {
            "type": "ir.actions.client",
            "tag": "display_notification",
            "params": {
                "title": _(
                    "Cannot compute days to prepare for %(boms)s: route info is missing for at least one component or for the final product.",
                    boms=", ".join(incomplete.mapped("display_name")),
                ),
                "sticky": False,
            },
        }

    @api.constrains("product_tmpl_id", "product_id", "type")
    def _check_kit_has_no_orderpoint(self):
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
    def _get_kit_domain(self, company=None):
        """Kit BoMs a company explodes -- the active one unless told otherwise.

        One definition for the three places that ask "is this product a kit":
        ``product.(template|product)._compute_is_kit`` and their ``search``
        counterparts. The three used to scope differently -- the compute to
        ``env.company``, the search to ``env.companies``, the quantity path to
        no company at all -- so the same product answered kit, not-a-kit and
        kit-with-no-BoM depending on which one you asked. ``env.company`` is
        the answer the field is documented to give
        (``@api.depends_context("company")``, and
        ``test_multicompany.test_is_kit_in_multi_company_env`` pins it), so it
        is the one the others adopt. ``company`` is for the callers that carry
        one of their own rather than reading the environment --
        ``stock.warehouse.orderpoint``'s kit constraint is scoped to the
        orderpoint's company, and spelled this domain a fourth time to say so.

        ``active`` is stated rather than left to ``active_test``, for the same
        reason ``_bom_find_domain`` states it: an archived BoM does not explode,
        so a caller reading these fields under ``active_test=False`` -- an
        archived-records view, or any code that set it -- must not be told the
        product is a kit. Measured before it was stated: under
        ``active_test=False`` the *search* returned a product whose only phantom
        BoM was archived, while the field and ``_bom_find`` both said no.
        """
        companies = company if company is not None else self.env.company
        return (
            Domain("type", "=", "phantom")
            & Domain("active", "=", True)
            & Domain("company_id", "in", [False, *companies.ids])
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
        """The BoM that applies to each of `products`, or nothing.

        Selection is `sequence, product_id, id`, and `product_id` sorts NULLS
        LAST: the lowest sequence wins, and within one sequence a BoM bound to
        the variant beats the template-wide one. A template-level BoM with a
        lower sequence therefore beats a variant-specific BoM with a higher one
        -- sequence is the only knob, which is what makes reordering able to
        change the answer, and why `_check_bom_cycle` watches `sequence`.

        :return: a defaultdict mapping each product to a BoM, empty for the
            products that have none. Service products are never in it.
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

    @api.model
    def _explosion_scratch(self):
        """The scratch an explosion memoises on, reusing the caller's if it has one.

        A caller that explodes several BoMs -- or the same BoM once per order --
        opens one of these around the whole batch, so the kit closure and the cost
        shares are resolved once each instead of once per call. `_explode` opens
        its own when nobody did, which keeps a lone explosion self-contained.

        Tested with ``is None``, never for truth: a scratch that has not been
        written to yet is an empty dict, so ``context.get(...) or ExplodeScratch()``
        hands back a *fresh* one exactly when the caller's is still empty -- which
        is every time, since it can only fill through the object it just replaced.
        """
        scratch = self.env.context.get("bom_cost_share_cache")
        return ExplodeScratch() if scratch is None else scratch

    def _explode(
        self, product, quantity, picking_type=False, never_attribute_values=False
    ):
        """Expand this BoM's kits into the leaf components they resolve to.

        :return: ``(boms_done, lines_done)`` -- the kit BoMs that were expanded
            and the leaf lines that survived, each paired with the values
            ``_prepare_bom_done_values`` / ``_prepare_line_done_values`` build.
            Both lists are in depth-first order and callers index into them
            positionally, so the traversal order is part of the contract.
        """
        self = self.with_context(bom_cost_share_cache=self._explosion_scratch())
        product_boms = self._get_kit_closure(
            product, picking_type, never_attribute_values
        )

        boms_done = [
            (
                self,
                self.env["mrp.bom.line"]._prepare_bom_done_values(
                    quantity, product, quantity, []
                ),
            )
        ]
        lines_done = []
        # A deque, not a list rebuilt by `bom_lines[1:]` and `[...] + bom_lines`:
        # both of those copy the whole frontier on every node, which is quadratic
        # in the size of the kit tree. `popleft` and `extendleft(reversed(...))`
        # visit the nodes in exactly the same order -- and that order is part of
        # this method's contract, since callers index into the two result lists
        # positionally.
        bom_lines = deque(
            (bom_line, product, quantity, False, frozenset((product.id,)))
            for bom_line in self.bom_line_ids
        )
        while bom_lines:
            current_line, current_product, current_qty, parent_line, ancestors = (
                bom_lines.popleft()
            )

            if current_line._skip_bom_line(current_product, never_attribute_values):
                continue

            line_quantity = current_qty * current_line.product_qty
            bom = product_boms.get(current_line.product_id)
            if bom:
                child_ancestors = ancestors | {current_line.product_id.id}
                converted_line_quantity = current_line._get_exploded_kit_quantity(
                    bom, line_quantity, ancestors
                )
                bom_lines.extendleft(
                    (
                        line,
                        current_line.product_id,
                        converted_line_quantity,
                        current_line,
                        child_ancestors,
                    )
                    for line in reversed(bom.bom_line_ids)
                )
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

    def _get_kit_closure(
        self, product, picking_type=False, never_attribute_values=False
    ):
        """Every kit BoM ``explode()`` can reach from this one, product by product.

        Resolved breadth-first, one search per level of the kit tree. Resolving
        it lazily during the depth-first walk instead costs one search per *node*
        -- measured 585 searches for a 585-node kit.

        The frontier carries ``(line, parent product)`` pairs and applies
        ``_skip_bom_line`` exactly as the explosion does, so the walk covers what
        the explosion will actually reach and no more; ignoring the skip makes
        this pass slower than the N+1 it replaces on a BoM whose lines are mostly
        variant-restricted.

        Tolerates an empty recordset, as ``explode()`` always has: several
        callers reach it through an optional ``bom_id``.

        Memoised on the explosion scratch when the caller supplies one. The answer
        is a function of the BoM, the variant, the operation type and the excluded
        attribute values only -- never of the quantity -- so every order built from
        the same BoM resolves the same closure, and ``_get_moves_raw_values``
        explodes once per *order*. Twenty orders on one BoM paid twenty identical
        `_bom_find` searches at each level of the kit tree.

        A hit rebuilds the mapping in the reader's environment rather than handing
        back the seeder's, so neither the records nor the dict are shared out.
        """
        picking_type = picking_type or self.picking_type_id
        scratch = self.env.context.get("bom_cost_share_cache")
        memo_key = (
            "kit_closure",
            self.id,
            product.id,
            picking_type.id,
            frozenset(never_attribute_values.ids) if never_attribute_values else (),
            # `_bom_find_domain` reads `context["company_id"]` whenever the company
            # it is handed is falsy, which is every company-less parent BoM. Keying
            # only on `self.id` would then let two readers in different companies
            # share one answer: measured, the second reader got the first's kit.
            self.company_id.id or self.env.context.get("company_id"),
        )
        if scratch is not None and (memoised := scratch.get(memo_key)) is not None:
            # Rebound to the reader's environment. Recordsets hash on
            # `(model, ids)`, so the lookup hits across environments, but the
            # values carry whichever one seeded them: a `sudo()` explosion that
            # shared a scratch handed the next reader superuser-bound BoMs, and
            # everything walked from them would have been read with those rights.
            return {
                product: bom.with_env(self.env) for product, bom in memoised.items()
            }
        product_boms = {}
        frontier = [(line, product) for line in self.bom_line_ids]
        while frontier:
            products = self.env["product.product"].browse()
            for line, parent in frontier:
                if line.product_id not in product_boms and not line._skip_bom_line(
                    parent, never_attribute_values
                ):
                    products |= line.product_id
            if not products:
                break
            bom_by_product = self._bom_find(
                products,
                picking_type=picking_type,
                company_id=self.company_id.id,
                bom_type="phantom",
            )
            frontier = []
            for child_product in products:
                bom = bom_by_product.get(child_product) or self.env["mrp.bom"]
                product_boms[child_product] = bom
                frontier += [(line, child_product) for line in bom.bom_line_ids]
        if scratch is not None:
            scratch[memo_key] = product_boms
        return product_boms

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

    def _update_outdated_bom_in_productions(self):
        """Restate `is_outdated_bom` for every order this BoM still drives.

        One statement, not two halves: a draft order of this BoM is outdated,
        a confirmed one is outdated exactly while its product still matches the
        BoM, and anything else keeps nothing. The two halves used to disagree --
        the marking side listed `product_variant_ids`, the unmarking side
        compared `product_tmpl_id` -- so an order on an *archived* variant
        matched neither and silently kept whatever flag it had.
        """
        if not self:
            return
        productions = self.env["mrp.production"].search(
            Domain("bom_id", "in", self.ids)
            & Domain("state", "in", ["draft", "confirmed"])
        )
        outdated, current = productions.browse(), productions.browse()
        skip_unmark = self.env.context.get("skip_bom_outdated_unmark")
        for production in productions:
            bom = production.bom_id
            if production.state == "draft" or self._matches_production(bom, production):
                outdated |= production
            else:
                current |= production
        outdated.filtered(lambda p: not p.is_outdated_bom).is_outdated_bom = True
        if not skip_unmark:
            current.filtered("is_outdated_bom").is_outdated_bom = False

    @api.model
    def _matches_production(self, bom, production):
        """Is `production` still making what `bom` describes?"""
        if bom.product_id:
            return production.product_id == bom.product_id
        return production.product_tmpl_id == bom.product_tmpl_id

    def _get_action_add_from_catalog_extra_context(self):
        return {
            **super()._get_action_add_from_catalog_extra_context(),
            "product_catalog_currency_id": self.env.company.currency_id.id,
        }

    def _default_order_line_values(self, child_field=False):
        default_data = super()._default_order_line_values(child_field)
        model = (
            self._fields[child_field].comodel_name if child_field else "mrp.bom.line"
        )
        # On an empty recordset, the way every other catalog model asks for the
        # "nothing here yet" payload.
        new_default_data = self.env[model]._get_product_catalog_lines_data()
        return {**default_data, **new_default_data}

    def _get_product_catalog_order_data(self, products, **kwargs):
        product_catalog = super()._get_product_catalog_order_data(products, **kwargs)
        for product in products:
            product_catalog[product.id] |= self._get_product_price_and_data(product)
        return product_catalog

    def _get_product_price_and_data(self, product):
        self.ensure_one()
        return {"price": product.standard_price}

    def _update_catalog_line_quantity(self, line, quantity, **kwargs):
        line.product_qty = quantity

    def _get_new_catalog_line_values(self, product_id, quantity, **kwargs):
        return {"product_id": product_id, "product_qty": quantity}

    def _get_mail_thread_data_attachments(self):
        res = super()._get_mail_thread_data_attachments()
        # `_get_extra_attachments` already accumulates over a recordset; calling
        # it per record threw that away and paid one search per BoM.
        for bom, attachments in self._get_extra_attachments_by_bom().items():
            res[bom.id] |= attachments
        return res

    def _get_extra_attachments(self):
        product_ids, template_ids = self._get_extra_attachment_targets()
        return self._search_extra_attachments(
            product_ids, template_ids
        ).ir_attachment_id

    def _get_extra_attachments_by_bom(self):
        """Same answer as ``_get_extra_attachments`` per BoM, in one search."""
        targets_by_bom = {bom: bom._get_extra_attachment_targets() for bom in self}
        all_products = OrderedSet()
        all_templates = OrderedSet()
        for product_ids, template_ids in targets_by_bom.values():
            all_products.update(product_ids)
            all_templates.update(template_ids)
        documents = self._search_extra_attachments(all_products, all_templates)
        by_product = defaultdict(lambda: self.env["product.document"])
        by_template = defaultdict(lambda: self.env["product.document"])
        for document in documents:
            target = (
                by_product if document.res_model == "product.product" else by_template
            )
            target[document.res_id] |= document
        result = {}
        for bom, (product_ids, template_ids) in targets_by_bom.items():
            documents = self.env["product.document"]
            for product_id in product_ids:
                documents |= by_product[product_id]
            for template_id in template_ids:
                documents |= by_template[template_id]
            result[bom] = documents.ir_attachment_id
        return result

    def _get_extra_attachment_targets(self):
        is_byproduct = self.env.user.has_group("mrp.group_mrp_byproducts")
        product_ids, template_ids = OrderedSet(), OrderedSet()
        for bom in self:
            product_ids.add(bom.product_id.id)
            template_ids.add(bom.product_tmpl_id.id)
            if is_byproduct:
                product_ids.update(bom.byproduct_ids.product_id.ids)
                template_ids.update(bom.byproduct_ids.product_id.product_tmpl_id.ids)
        return product_ids, template_ids

    @api.model
    def _search_extra_attachments(self, product_ids, template_ids):
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
        return self.env["product.document"].search(domain)

    @api.model
    def _skip_for_no_variant(
        self, product, bom_attribute_values, never_attribute_values=False
    ):
        no_variant_bom_attributes = bom_attribute_values.filtered(
            lambda av: av.attribute_id.create_variant == "no_variant"
        )
        other_attribute_valid = product._match_all_variant_values(
            bom_attribute_values - no_variant_bom_attributes
        )
        if not no_variant_bom_attributes:
            return not other_attribute_valid
        if not never_attribute_values:
            return True

        # A line restricted to a no_variant value applies only when that exact
        # value was asked for. The loop answers "no attribute in common" on its
        # own, which is why there is no separate early return for it.
        never_values_by_attribute = never_attribute_values.grouped("attribute_id")
        for attribute, values in no_variant_bom_attributes.grouped(
            "attribute_id"
        ).items():
            never_values = never_values_by_attribute.get(attribute)
            if never_values and values & never_values:
                return not other_attribute_valid
        return True

    @api.depends_context("orderpoint_id", "default_orderpoint_id")
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
            domain = Domain("action", "=", "manufacture") & Domain(
                "company_id", "in", [orderpoint.company_id.id, False]
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
