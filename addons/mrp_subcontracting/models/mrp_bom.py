from collections import defaultdict

from odoo import api, fields, models
from odoo.exceptions import ValidationError
from odoo.fields import Domain
from odoo.libs.debug_log import DebugLog
from odoo.tools import TransactionMemo

SUBCONTRACT_BOM_BY_PRODUCT = TransactionMemo(
    "mrp.bom.subcontract_by_product", invalidated_by=("mrp.bom",)
)

_debug = DebugLog(__name__)


class MrpBom(models.Model):
    _inherit = "mrp.bom"

    type = fields.Selection(
        selection_add=[("subcontract", "Subcontracting")],
        ondelete={
            "subcontract": lambda recs: recs.write({"type": "normal", "active": False})
        },
    )
    subcontractor_ids = fields.Many2many(
        comodel_name="res.partner",
        relation="mrp_bom_subcontractor",
        string="Subcontractors",
        check_company=True,
    )

    def _get_subcontract_bom_by_product(
        self,
        product,
        picking_type=None,
        company_id=False,
        bom_type="subcontract",
        subcontractor=False,
    ):
        if not subcontractor:
            _debug.logic("subcontract_bom", product=product.id, by="no_subcontractor")
            return self.env["mrp.bom"]
        memo = SUBCONTRACT_BOM_BY_PRODUCT(self.env)
        scope = (
            self.env.uid,
            self.env.su,
            tuple(self.env.companies.ids),
            picking_type.id if picking_type else False,
            company_id,
            bom_type,
            tuple(subcontractor.ids),
        )
        if (scope, product.id) not in memo:
            # one search answers every product fetched alongside this one, as
            # orderpoints and moves ask for them one at a time
            batch = (
                product.browse(product._prefetch_ids).filtered(
                    lambda candidate: (scope, candidate.id) not in memo
                )
                | product
            )
            found = self._search_subcontract_bom_by_product(
                batch, picking_type, company_id, bom_type, subcontractor
            )
            for candidate in batch:
                memo[scope, candidate.id] = found[candidate].id
            _debug.logic(
                "subcontract_bom",
                product=product.id,
                subcontractor=subcontractor.id,
                batch=len(batch),
            )
        return self.browse(memo[scope, product.id])

    def _search_subcontract_bom_by_product(
        self, products, picking_type, company_id, bom_type, subcontractor
    ):
        domain = self._get_domain_bom(
            products,
            picking_type=picking_type,
            company_id=company_id,
            bom_type=bom_type,
        ) & Domain("subcontractor_ids", "parent_of", subcontractor.ids)
        products_by_template = defaultdict(products.browse)
        for product in products:
            products_by_template[product.product_tmpl_id] |= product
        found = defaultdict(lambda: self.env["mrp.bom"])
        for bom in self.search(domain, order="sequence, product_id, id"):
            matched = (
                bom.product_id & products
                if bom.product_id
                else products_by_template[bom.product_tmpl_id]
            )
            for product in matched:
                if product not in found:
                    found[product] = bom
        return found

    @api.constrains("operation_ids", "byproduct_ids", "type")
    def _check_subcontracting_no_operation(self):
        if self.filtered_domain(
            [
                ("type", "=", "subcontract"),
                "|",
                ("operation_ids", "!=", False),
                ("byproduct_ids", "!=", False),
            ]
        ):
            _debug.logic("bom_refused", reason="subcontract_with_operations", boms=self)
            raise ValidationError(
                self.env._(
                    "You can not set a Bill of Material with operations or by-product line as subcontracting."
                )
            )

    def _get_subcontracting_seller(self, product, quantity):
        self.check_singleton()
        if not product:
            return self.product_tmpl_id.seller_ids.filtered(
                lambda seller: seller.partner_id in self.subcontractor_ids
            )[:1]
        return product._select_seller(
            quantity=quantity,
            uom_id=self.product_uom_id,
            params={"subcontractor_ids": self.subcontractor_ids},
        )

    def _get_subcontracting_cost(self, seller, quantity):
        self.check_singleton()
        company = self.company_id or self.env.company
        price = seller.currency_id._convert(
            seller.price, company.currency_id, company, fields.Date.today()
        )
        return company.currency_id.round(
            seller.product_uom_id._get_price_in_unit(price, self.product_uom_id)
            * quantity
        )

    def _get_rolled_up_cost(self, product, quantity, as_component=False):
        cost = super()._get_rolled_up_cost(product, quantity, as_component)
        if self.type != "subcontract":
            return cost
        seller = self._get_subcontracting_seller(product, quantity)
        if seller:
            cost += self._get_subcontracting_cost(seller, quantity)
        return cost
