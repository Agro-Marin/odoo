from odoo import fields, models
from odoo.libs.debug_log import DebugLog

_debug = DebugLog(__name__)


class ProductTemplate(models.Model):
    _inherit = "product.template"

    def _get_product_accounts(self, fiscal_pos=None):
        accounts = super()._get_product_accounts(fiscal_pos=fiscal_pos)
        if self.categ_id:
            production_account = self.categ_id.property_stock_account_production_cost_id
        else:
            ProductCategory = self.env["product.category"]
            production_account = (
                self.valuation == "real_time"
                and ProductCategory._fields[
                    "property_stock_account_production_cost_id"
                ].get_company_dependent_fallback(ProductCategory)
            ) or self.env["account.account"]
        accounts.update(
            self._map_product_accounts({"production": production_account}, fiscal_pos)
        )
        return accounts

    def action_bom_cost(self):
        templates = self.filtered(
            lambda t: t.product_variant_count == 1 and t.bom_count > 0
        )
        if templates:
            templates.mapped("product_variant_id").action_bom_cost()

    def button_bom_cost(self):
        templates = self.filtered(
            lambda t: t.product_variant_count == 1 and t.bom_count > 0
        )
        if templates:
            templates.mapped("product_variant_id").button_bom_cost()


class ProductProduct(models.Model):
    _inherit = "product.product"

    def button_bom_cost(self):
        self.check_singleton()
        self._update_standard_price_from_bom()

    def action_bom_cost(self):
        for product in self:
            product._update_standard_price_from_bom()

    def _update_standard_price_from_bom(self):
        self.check_singleton()
        bom = self.env["mrp.bom"]._get_bom_by_product(self)[self]
        if bom:
            self.standard_price = self._get_bom_price(bom)
        else:
            bom = self.env["mrp.bom"].search(
                [("byproduct_ids.product_id", "=", self.id)],
                order="sequence, product_id, id",
                limit=1,
            )
            if bom:
                price = self._get_bom_price(bom, byproduct_bom=True)
                if price:
                    self.standard_price = price

    def _get_bom_price(self, bom, byproduct_bom=False):
        self.check_singleton()
        if not bom:
            _debug.logic("bom_price", product=self.id, by="no_bom")
            return 0
        if not byproduct_bom:
            total = bom._get_rolled_up_cost(self, bom.product_qty)
            share = bom._get_finished_cost_share(self)
            _debug.logic(
                "bom_price",
                product=self.id,
                bom=bom.id,
                by="rolled_up",
                total=total,
                share=share,
            )
            return bom.product_uom_id._get_price_in_unit(
                total * share / bom.product_qty, self.uom_id
            )
        product = bom.product_id or bom.product_tmpl_id.product_variant_id
        byproduct_lines = bom.byproduct_ids.filtered(
            lambda b: b.product_id == self and b.cost_share != 0
        )
        product_uom_qty = 0
        for line in byproduct_lines:
            product_uom_qty += line.product_uom_id._get_quantity_in_unit(
                line.product_qty, self.uom_id, round=False
            )
        byproduct_cost_share = sum(byproduct_lines.mapped("cost_share"))
        total = bom._get_rolled_up_cost(product, bom.product_qty)
        _debug.logic(
            "bom_price",
            product=self.id,
            bom=bom.id,
            by="byproduct_share",
            total=total,
            share=byproduct_cost_share,
        )
        if byproduct_cost_share and product_uom_qty:
            return total * byproduct_cost_share / 100 / product_uom_qty
        return 0.0

    def _compute_value(self):
        non_kit_products = self.filtered(lambda product: not product.is_kit)
        super(ProductProduct, non_kit_products)._compute_value()
        kit_products = self - non_kit_products
        kit_products.company_currency_id = self.env.company.currency_id
        kit_products.total_value = 0.0
        kit_products.avg_cost = 0.0


class ProductCategory(models.Model):
    _inherit = "product.category"

    property_stock_account_production_cost_id = fields.Many2one(
        comodel_name="account.account",
        string="Production Account",
        company_dependent=True,
        ondelete="restrict",
        check_company=True,
        help="""This account will be used as a valuation counterpart for both components and final products for manufacturing orders.
                If there are any workcenter/employee costs, this value will remain on the account once the production is completed.""",
    )
