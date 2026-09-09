/** @odoo-module native */
import { PurchaseProductCatalogKanbanRecord } from "@purchase/product_catalog/kanban_record";

import { ProductCatalogPurchaseSuggestOrderLine } from "./purchase_order_line.js";

export class ProductCatalogPurchaseSuggestKanbanRecord extends PurchaseProductCatalogKanbanRecord {
    getRecordClasses(...args) {
        const classes = super.getRecordClasses(...args) || "";
        const catalogData = this.productCatalogData || {};

        if (
            catalogData.suggested_qty &&
            catalogData.suggested_qty === catalogData.quantity
        ) {
            return classes + " o_hide_suggest_qty";
        }
        return classes;
    }

    get orderLineComponent() {
        return ProductCatalogPurchaseSuggestOrderLine;
    }

    addProduct() {
        const { min_qty = 1, suggested_qty = 0 } = this.productCatalogData;
        let quantity_to_add = Math.max(min_qty, suggested_qty, 1);
        if (this.productCatalogData.uomFactor) {
            quantity_to_add = Math.ceil(
                quantity_to_add / this.productCatalogData.uomFactor,
            );
        }
        super.addProduct(quantity_to_add);
    }
}
