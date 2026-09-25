/** @odoo-module native */
import { registry } from "@web/core/registry";
import { kanbanView } from "@web/views/kanban";

import { ProductCatalogKanbanController } from "./kanban_controller.js";
import { ProductCatalogKanbanModel } from "./kanban_model.js";
import { ProductCatalogKanbanRenderer } from "./kanban_renderer.js";
import { ProductCatalogSearchModel } from "./search/search_model.js";
import { ProductCatalogSearchPanel } from "./search/search_panel.js";

export const productCatalogKanbanView = {
    ...kanbanView,
    Controller: ProductCatalogKanbanController,
    Model: ProductCatalogKanbanModel,
    Renderer: ProductCatalogKanbanRenderer,
    SearchModel: ProductCatalogSearchModel,
    SearchPanel: ProductCatalogSearchPanel,
};

registry.category("views").add("product_kanban_catalog", productCatalogKanbanView);
