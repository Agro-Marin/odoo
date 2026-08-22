/** @odoo-module native */
import { ProductCatalogKanbanRecord } from "@product/product_catalog/kanban_record";

import { ProductCatalogPurchaseOrderLine } from "./purchase_order_line/purchase_order_line.js";

export class PurchaseProductCatalogKanbanRecord extends ProductCatalogKanbanRecord {
    get orderLineComponent() {
        return ProductCatalogPurchaseOrderLine;
    }
}
