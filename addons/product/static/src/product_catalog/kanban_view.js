/** @odoo-module native */
import { registry } from "@web/core/registry";
import { kanbanView } from "@web/views/kanban/kanban_view";

import { ProductCatalogKanbanController } from "./kanban_controller.js";
import { ProductCatalogKanbanModel } from "./kanban_model.js";
import { ProductCatalogKanbanRenderer } from "./kanban_renderer.js";

export const productCatalogKanbanView = {
    ...kanbanView,
    Controller: ProductCatalogKanbanController,
    Model: ProductCatalogKanbanModel,
    Renderer: ProductCatalogKanbanRenderer,
};

registry.category("views").add("product_kanban_catalog", productCatalogKanbanView);
