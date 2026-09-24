/** @odoo-module native */
import { ProductCatalogOrderLine } from "@product/product_catalog/order_line/order_line";
import { useProductCatalogContext } from "@product/product_catalog/product_catalog_context";
import { patch } from "@web/core/utils/patch";

patch(ProductCatalogOrderLine.prototype, {
    setup() {
        super.setup(...arguments);
        this.catalogContext = useProductCatalogContext();
    },

    get showPrice() {
        return (
            super.showPrice && this.catalogContext.orderResModel !== "mrp.production"
        );
    },
});
