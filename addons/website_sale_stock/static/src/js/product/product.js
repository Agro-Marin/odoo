/** @odoo-module native */
import { patch } from "@web/core/utils/patch";
import { Product } from "@sale/js/product/product";
import { useWebsiteSaleStockContext } from "@website_sale_stock/website_sale_stock_context";

patch(Product, {
    props: {
        ...Product.props,
        qty_free: { type: Number, optional: true },
    },
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
