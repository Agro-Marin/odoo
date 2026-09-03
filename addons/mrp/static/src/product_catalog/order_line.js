/** @odoo-module native */
import { ProductCatalogOrderLine } from "@product/product_catalog/order_line/order_line";
import { patch } from "@web/core/utils/patch";

const NO_PRICE_MODELS = ["mrp.production", "mrp.workorder"];

patch(ProductCatalogOrderLine.prototype, {
    get showPrice() {
        return super.showPrice && !NO_PRICE_MODELS.includes(this.env.orderResModel);
    },
});
