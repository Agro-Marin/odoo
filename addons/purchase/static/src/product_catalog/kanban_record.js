/** @odoo-module native */
import { ProductCatalogKanbanRecord } from "@product/product_catalog/kanban_record";
import { useService } from "@web/core/utils/hooks";
import { patch } from "@web/core/utils/patch";

import { ProductCatalogPurchaseOrderLine } from "./purchase_order_line/purchase_order_line.js";

patch(ProductCatalogKanbanRecord.prototype, {
    setup() {
        super.setup();
        this.orm = useService("orm");
    },

    get orderLineComponent() {
        if (this.env.orderResModel === "purchase.order") {
            return ProductCatalogPurchaseOrderLine;
        }
        return super.orderLineComponent;
    },
});
