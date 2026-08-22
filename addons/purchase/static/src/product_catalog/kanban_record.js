/** @odoo-module native */
import { ProductCatalogKanbanRecord } from "@product/product_catalog/kanban_record";

import { ProductCatalogPurchaseOrderLine } from "./purchase_order_line/purchase_order_line.js";

/**
 * Catalog card for a purchase order.
 *
 * A subclass, not a `patch` on the base prototype with an
 * `env.orderResModel === "purchase.order"` test: the renderer that mounts this
 * is already purchase-specific, so the model is known statically and the check
 * only re-derived at render time what the view knew at build time. It also made
 * every catalog card in the system — sale's, account's — walk one more `super`
 * hop through a comparison that could never match for them.
 */
export class PurchaseProductCatalogKanbanRecord extends ProductCatalogKanbanRecord {
    get orderLineComponent() {
        return ProductCatalogPurchaseOrderLine;
    }
}
