from odoo import api, fields, models
from odoo.libs.debug_log import DebugLog

_debug = DebugLog(__name__)


class ProductProduct(models.Model):
    _inherit = "product.product"

    tax_string = fields.Char(compute="_compute_tax_string")

    @_debug.perf.timed
    def _get_tax_included_unit_price(
        self,
        company,
        currency,
        document_date,
        document_type,
        is_refund_document=False,
        product_uom_id=None,
        product_currency=None,
        product_price_unit=None,
        product_taxes=None,
        fiscal_position=None,
    ):
        self.check_singleton()
        company.check_singleton()

        if not document_type:
            raise ValueError("document_type is required")

        if product_uom_id is None:
            product_uom_id = self.uom_id
        if not product_currency:
            if document_type == "sale":
                product_currency = self.currency_id
            elif document_type == "purchase":
                product_currency = company.currency_id
        if product_price_unit is None:
            if document_type == "sale":
                product_price_unit = self.with_company(company).lst_price
            elif document_type == "purchase":
                product_price_unit = self.with_company(company).standard_price
            else:
                _debug.logic(
                    "unit_price_skipped",
                    product=self,
                    document_type=document_type,
                    reason="no_price_source",
                )
                return 0.0
        if product_taxes is None:
            if document_type == "sale":
                product_taxes = self.taxes_id
            elif document_type == "purchase":
                product_taxes = self.supplier_taxes_id
        if product_taxes:
            product_taxes = product_taxes._filter_taxes_by_company(company)
        if product_uom_id and self.uom_id != product_uom_id:
            product_price_unit = self.uom_id._get_price_in_unit(
                product_price_unit, product_uom_id
            )

        if product_taxes and fiscal_position:
            product_price_unit = self._get_tax_included_unit_price_from_price(
                product_price_unit,
                product_taxes,
                fiscal_position=fiscal_position,
            )

        if product_currency and currency != product_currency:
            product_price_unit = product_currency._convert(
                product_price_unit, currency, company, document_date, round=False
            )

        _debug.logic(
            "unit_price_resolved",
            product=self,
            company=company,
            document_type=document_type,
            taxes=product_taxes,
            fiscal_position=fiscal_position,
            currency=currency,
            product_currency=product_currency,
            price=product_price_unit,
        )
        return product_price_unit

    def _get_tax_included_unit_price_from_price(
        self,
        product_price_unit,
        product_taxes,
        fiscal_position=None,
        product_taxes_after_fp=None,
    ):
        if not product_taxes:
            return product_price_unit

        if product_taxes_after_fp is None:
            if not fiscal_position:
                return product_price_unit

            product_taxes_after_fp = fiscal_position.map_tax(product_taxes)

        return product_taxes._adapt_price_unit_to_another_taxes(
            price_unit=product_price_unit,
            product=self,
            original_taxes=product_taxes,
            new_taxes=product_taxes_after_fp,
        )

    @api.depends("lst_price", "product_tmpl_id", "taxes_id")
    @api.depends_context("company")
    def _compute_tax_string(self):
        for record in self:
            record.tax_string = record.product_tmpl_id._prepare_tax_string(
                record.lst_price
            )
