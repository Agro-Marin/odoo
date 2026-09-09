/** @odoo-module native */
import { ProductCatalogKanbanRecord } from "@product/product_catalog/kanban_record";
import { patch } from "@web/core/utils/patch";

import { ProductCatalogSaleOrderLine } from "./sale_order_line/sale_order_line.js";

patch(ProductCatalogKanbanRecord.prototype, {
    updateQuantity(quantity) {
        if (
            this.env.orderResModel !== "sale.order" ||
            this.productCatalogData.productType === "service"
        ) {
            super.updateQuantity(...arguments);
        } else if (
            this.productCatalogData.quantity === this.productCatalogData.deliveredQty &&
            quantity < this.productCatalogData.quantity
        ) {
            this.props.record.load();
            this.props.record.model.notify();
        } else {
            super.updateQuantity(
                Math.max(quantity, this.productCatalogData.deliveredQty),
            );
        }
    },

    get orderLineComponent() {
        if (this.env.orderResModel === "sale.order") {
            return ProductCatalogSaleOrderLine;
        }
        return super.orderLineComponent;
    },
});
