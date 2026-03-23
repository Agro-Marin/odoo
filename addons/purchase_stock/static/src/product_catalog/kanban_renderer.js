/** @odoo-module native */
import { patch } from "@web/core/utils/patch";
import { PurchaseProductCatalogKanbanRenderer } from "@purchase/product_catalog/kanban_renderer";
import { ProductCatalogPurchaseSuggestKanbanRecord } from "./record/kanban_record.js";

patch(PurchaseProductCatalogKanbanRenderer, {
    components: {
        ...PurchaseProductCatalogKanbanRenderer.components,
        KanbanRecord: ProductCatalogPurchaseSuggestKanbanRecord,
    },
});
