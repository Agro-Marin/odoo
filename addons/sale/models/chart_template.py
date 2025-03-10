from odoo import models


class AccountChartTemplate(models.AbstractModel):
    """Extends the 'account.chart.template' model to include specific property accounts for downpayments.

    This module adds support for defining a default account for downpayments at the product category level,
    ensuring proper accounting treatment for downpayment transactions in sales operations.
    """

    _inherit = "account.chart.template"

    # ------------------------------------------------------------
    # HOOKS
    # ------------------------------------------------------------

    def _get_property_accounts(self, additional_properties):
        property_accounts = super()._get_property_accounts(additional_properties)
        property_accounts["property_account_downpayment_categ_id"] = "product.category"
        return property_accounts
