/** @odoo-module native */
import { patch } from "@web/core/utils/patch";
import { Product, productProps } from "@sale/js/product/product";
import { useWebsiteSaleStockContext } from "@website_sale_stock/js/product_configurator_dialog/website_sale_stock_context";

Object.assign(productProps, {
    qty_free: { type: Number, optional: true },
});

patch(Product.prototype, {
    setup() {
        super.setup(...arguments);
        this.websiteSaleStockContext = useWebsiteSaleStockContext();
    },

    /**
     * @return {Boolean}
     */
    isOutOfStock() {
        return !this.websiteSaleStockContext.isQuantityAllowed(this.props, 1);
    },
});
