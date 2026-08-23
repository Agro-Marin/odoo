from odoo import api, fields, models
from odoo.exceptions import ValidationError


class MixinBomComponent(models.AbstractModel):
    """A quantity of a product on a BoM: a component line or a by-product.

    The two models are the same shape -- a product, how much of it, in which
    unit, produced or consumed at which operation -- and had said so twice:
    two byte-identical `_get_product_catalog_lines_data`, two `_check_product
    _uom_id_category` differing only in their message, two `action_add_from
    _catalog` differing only in the one2many they write back to.

    Only what genuinely differs is left to the models: the field labels, whether
    the product column is indexed, and the sentence a translator reads. The
    catalog child field is a class attribute rather than a method because it is
    a fact about the model, not a decision.
    """

    _name = "mixin.bom.component"
    _inherit = ["mixin.bom.variant.line"]
    _description = "A quantity of a product on a BoM"
    _rec_name = "product_id"
    _order = "sequence, id"
    _check_company_auto = True

    #: one2many on `mrp.bom` that holds records of this model
    _bom_child_field = None

    product_id = fields.Many2one(
        "product.product", "Product", required=True, check_company=True, index=True
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
    sequence = fields.Integer(
        "Sequence", help="Gives the sequence order when displaying."
    )
    allowed_operation_ids = fields.One2many(
        "mrp.routing.workcenter", related="bom_id.operation_ids"
    )
    operation_id = fields.Many2one(
        "mrp.routing.workcenter",
        "Operation",
        check_company=True,
        domain="[('id', 'in', allowed_operation_ids)]",
    )

    _qty_not_negative = models.Constraint(
        "CHECK (product_qty >= 0)",
        "A quantity on a bill of materials cannot be negative.",
    )

    @api.depends("product_id")
    def _compute_product_uom_id(self):
        """Stamp the product's own unit, unless the record already names one.

        `precompute=True` makes this run before the INSERT, so a row created
        without a unit never touches the database with the wrong one. It
        replaces a `default=` that returned whichever `uom.uom` had the lowest
        id -- a value the unit-consistency constraint below then rejected.
        """
        for record in self:
            record.product_uom_id = record.product_id.uom_id

    @api.constrains("product_uom_id", "product_id")
    def _check_product_uom_id_category(self):
        for record in self:
            product_uom = record.product_id.uom_id
            if (
                record.product_uom_id
                and product_uom
                and not record.product_uom_id._has_common_reference(product_uom)
            ):
                raise ValidationError(record._get_uom_mismatch_message())

    def _get_uom_mismatch_message(self):
        """The sentence for a unit that does not measure the product's own.

        A hook rather than a class attribute because the string has to be a
        literal at the call site for `babel` to extract it.
        """
        raise NotImplementedError

    def action_add_from_catalog(self):
        bom = self.env["mrp.bom"].browse(self.env.context.get("order_id"))
        return bom.with_context(
            child_field=self._bom_child_field
        ).action_add_from_catalog()

    def _get_product_catalog_lines_data(self, **kwargs):
        if not self:
            return {"quantity": 0}
        self.product_id.ensure_one()
        return {
            **self[0].bom_id._get_product_price_and_data(self[0].product_id),
            # Converted to the product's own unit, not to each line's: summing
            # 1 kg and 500 g in their own units reports 501.
            "quantity": sum(
                self.mapped(
                    lambda line: line.product_uom_id._compute_quantity_report(
                        qty=line.product_qty,
                        to_unit=line.product_id.uom_id,
                    )
                )
            ),
            "readOnly": len(self) > 1,
            "uomDisplayName": (len(self) == 1 and self.product_uom_id.display_name)
            or self.product_id.uom_id.display_name,
        }
