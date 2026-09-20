from odoo.http import request, route
from odoo.tools.image import image_data_uri

from odoo.addons.sale.controllers.combo_configurator import (
    SaleComboConfiguratorController,
)
from odoo.addons.website_sale.controllers.main import WebsiteSale


class WebsiteSaleComboConfiguratorController(
    SaleComboConfiguratorController, WebsiteSale
):
    @route(
        route="/website_sale/combo_configurator/get_data",
        type="jsonrpc",
        auth="public",
        website=True,
        readonly=True,
    )
    def website_sale_combo_configurator_get_data(self, *args, **kwargs):
        self._update_currency_and_pricelist(kwargs)
        request.update_context(display_default_code=False)
        return super().sale_combo_configurator_get_data(*args, **kwargs)

    @route(
        route="/website_sale/combo_configurator/get_price",
        type="jsonrpc",
        auth="public",
        website=True,
        readonly=True,
    )
    def website_sale_combo_configurator_get_price(self, *args, **kwargs):
        self._update_currency_and_pricelist(kwargs)
        return super().sale_combo_configurator_get_price(*args, **kwargs)

    def _get_combo_item_data(
        self,
        combo,
        combo_item,
        selected_combo_item,
        date,
        currency,
        pricelist,
        **kwargs,
    ):
        data = super()._get_combo_item_data(
            combo, combo_item, selected_combo_item, date, currency, pricelist, **kwargs
        )
        if not combo_item.product_id.sudo(False).has_access("read") and (
            combo_item_image := combo_item.product_id.image_256
        ):
            data["product"]["image_src"] = image_data_uri(combo_item_image)
        return data
