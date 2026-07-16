/** @odoo-module native */
import { purchaseProductCatalogKanbanView } from "@purchase/product_catalog/kanban_view";
import { patch } from "@web/core/utils/patch";

import { PurchaseSuggestCatalogKanbanController } from "./kanban_controller.js";
import { PurchaseSuggestCatalogKanbanModel } from "./kanban_model.js";
import { PurchaseStockProductCatalogSearchModel } from "./search/search_model.js";
import { PurchaseSuggestCatalogSearchPanel } from "./search/search_panel.js";

patch(purchaseProductCatalogKanbanView, {
    Controller: PurchaseSuggestCatalogKanbanController,
    SearchPanel: PurchaseSuggestCatalogSearchPanel,
    Model: PurchaseSuggestCatalogKanbanModel,
    SearchModel: PurchaseStockProductCatalogSearchModel,
});
