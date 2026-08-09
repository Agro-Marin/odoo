from odoo import _, api, fields, models
from odoo.exceptions import ValidationError


class ProductComboItem(models.Model):
    _name = "product.combo.item"
    _description = "Product Combo Item"
    _check_company_auto = True

    product_id = fields.Many2one(
        comodel_name="product.product",
        string="Options",
        required=True,
        check_company=True,
        domain=[("type", "!=", "combo")],
        ondelete="restrict",
    )
    currency_id = fields.Many2one(
        related="product_id.currency_id",
        comodel_name="res.currency",
    )
    lst_price = fields.Float(
        related="product_id.lst_price",
        string="Original Price",
        min_display_digits="Product Price",
    )
    combo_id = fields.Many2one(
        comodel_name="product.combo",
        required=True,
        ondelete="cascade",
        index=True,
    )
    company_id = fields.Many2one(
        related="combo_id.company_id",
        store=True,
        precompute=True,
    )
    extra_price = fields.Float(
        string="Extra Price",
        min_display_digits="Product Price",
        default=0.0,
    )

    @api.constrains("product_id")
    def _check_product_id_no_combo(self):
        if any(combo_item.product_id.type == "combo" for combo_item in self):
            raise ValidationError(
                _('A combo choice can\'t contain products of type "combo".')
            )

    def unlink(self):
        """Keep `product.combo`'s "at least 1 choice" invariant.

        That constraint lives on `product.combo` and only fires when the combo
        itself is created/written. Deleting the items directly never writes the
        parent, so the combo was left empty -- and an empty combo prices its
        choice at 0 through `base_price`.

        The check is deferred to precommit rather than done here: within a
        single write on the parent, the ORM flushes *deletes before creates*
        (see `one2many.write_real`), so replacing every item of a combo passes
        through a transient empty state that must not be rejected.
        """
        combo_ids = set(self.combo_id.ids)
        res = super().unlink()
        if combo_ids:
            self.env.cr.precommit.data.setdefault(
                "product.combo.emptied", set()
            ).update(combo_ids)
            self.env.cr.precommit.add(self._check_combos_not_emptied)
        return res

    @api.model
    def _check_combos_not_emptied(self):
        combo_ids = self.env.cr.precommit.data.pop("product.combo.emptied", ())
        # Combos deleted in the same transaction are fine: their items are meant
        # to go with them.
        combos = self.env["product.combo"].browse(combo_ids).exists()
        if not combos:
            return
        remaining = dict(
            self._read_group(
                [("combo_id", "in", combos.ids)], ["combo_id"], ["__count"]
            )
        )
        emptied = combos.filtered(lambda combo: not remaining.get(combo))
        if emptied:
            raise ValidationError(
                _(
                    "A combo must keep at least 1 choice: %(combos)s would be left"
                    " empty. Delete the combo itself instead.",
                    combos=", ".join(emptied.mapped("name")),
                )
            )
