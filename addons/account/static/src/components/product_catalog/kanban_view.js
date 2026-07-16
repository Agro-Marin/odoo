/** @odoo-module native */
import { productCatalogKanbanView } from "@product/product_catalog/kanban_view";
import { patch } from "@web/core/utils/patch";

import { AccountProductCatalogSearchModel } from "./search/search_model.js";
import { AccountProductCatalogSearchPanel } from "./search/search_panel.js";

patch(productCatalogKanbanView, {
    SearchModel: AccountProductCatalogSearchModel,
    SearchPanel: AccountProductCatalogSearchPanel,
});
