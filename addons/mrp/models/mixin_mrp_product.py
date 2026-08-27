from odoo import fields, models


class MixinMrpProduct(models.AbstractModel):
    """What `product.template` and `product.product` say identically about BoMs.

    The two carried six members that differed in exactly one token: which field
    names this product on `mrp.bom.line` and on `stock.move`, and which
    one2many holds the BoMs archived along with it. Both are class attributes
    here, and the bodies are written once.

    Only what is genuinely the same lives here. `bom_count`, `mrp_product_qty`
    and `is_kit` have one shape and two different derivations -- a variant is a
    kit through a BoM of its own *or* one its template carries for every
    variant, and a template's manufactured quantity is the sum over its variants
    -- so the fields are declared here and each model computes them itself.

    The mixin sits last in the MRO (`_inherit = ["<model>", "mixin.mrp.product"]`),
    so every `super()` call below resolves to a BaseModel-level implementation:
    `action_archive` from `odoo.orm.models.mixins.lifecycle` and
    `_get_backend_root_menu_ids` from `mail`'s `base` extension. Nothing here may
    call `super()` on a method that only `product.template` defines.
    """

    _name = "mixin.mrp.product"
    _description = "BoM behaviour shared by product.template and product.product"

    #: field naming this product on `mrp.bom.line` and `stock.move`
    _mrp_product_field = None
    #: one2many holding the BoMs archived and unarchived along with this record
    _mrp_bom_field = None

    bom_count = fields.Integer(
        "# Bill of Material", compute="_compute_bom_count", compute_sudo=False
    )
    used_in_bom_count = fields.Integer(
        "# BoM Where Used", compute="_compute_used_in_bom_count", compute_sudo=False
    )
    mrp_product_qty = fields.Float(
        "Manufactured",
        digits="Product Unit",
        compute="_compute_mrp_product_qty",
        compute_sudo=False,
    )
    is_kit = fields.Boolean(compute="_compute_is_kit", search="_search_is_kit")

    def _get_mrp_variants(self):
        """The variants this record stands for -- itself, or the template's."""
        raise NotImplementedError

    def _compute_used_in_bom_count(self):
        counts = {
            record.id: count
            for record, count in self.env["mrp.bom.line"]._read_group(
                [(self._mrp_product_field, "in", self.ids)],
                [self._mrp_product_field],
                ["bom_id:count_distinct"],
            )
        }
        for record in self:
            record.used_in_bom_count = counts.get(record.id, 0)

    def action_used_in_bom(self):
        self.ensure_one()
        action = self.env["ir.actions.actions"]._get_action_dict_by_xml_id(
            "mrp.mrp_bom_form_action"
        )
        action["domain"] = [(f"bom_line_ids.{self._mrp_product_field}", "=", self.id)]
        return action

    def action_view_mos(self):
        action = self.env["ir.actions.actions"]._get_action_dict_by_xml_id(
            "mrp.mrp_production_action"
        )
        action["domain"] = [
            ("state", "=", "done"),
            (
                "move_finished_ids",
                "any",
                [
                    (self._mrp_product_field, "in", self.ids),
                    ("state", "!=", "cancel"),
                    ("picked", "=", True),
                ],
            ),
        ]
        action["context"] = {"search_default_filter_plan_date": 1}
        return action

    def write(self, vals):
        if "active" in vals:
            # Before `super()`, and reading `active` off the record: the point
            # is to catch the ones whose flag is actually changing, which is
            # unanswerable once the write has landed.
            self.filtered(lambda record: record.active != vals["active"]).with_context(
                active_test=False
            )[self._mrp_bom_field].write({"active": vals["active"]})
        return super().write(vals)

    def _get_still_used_bom_lines(self):
        """Live BoM lines consuming these products. Call *before* archiving.

        `action_archive` itself cannot live on this mixin, and the reason is
        worth writing down: `BaseModel.action_archive` is typed `-> None`, and
        `product.product`'s override in `product` honours that by calling
        `super()` without returning its result. mrp's notification only ever
        reached the client because mrp's own class sits *above* `product`'s in
        the MRO -- a trailing mixin sits below it, and the action is swallowed.
        So the override stays where the MRO puts it first, and only the lookup
        is shared.
        """
        return self.env["mrp.bom.line"].search(
            [
                ("product_id", "in", self._get_mrp_variants().ids),
                ("bom_id.active", "=", True),
            ]
        )

    def _get_backend_root_menu_ids(self):
        return super()._get_backend_root_menu_ids() + [
            self.env.ref("mrp.menu_mrp_root").id
        ]
