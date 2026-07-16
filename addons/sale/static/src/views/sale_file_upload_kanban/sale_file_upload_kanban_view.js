/** @odoo-module native */
import { fileUploadKanbanView } from "@account/views/file_upload_kanban/file_upload_kanban_view";
import { registry } from "@web/core/registry";

import { SaleFileUploadKanbanController } from "./sale_file_upload_kanban_controller.js";
import { SaleFileUploadKanbanRenderer } from "./sale_file_upload_kanban_renderer.js";

export const saleFileUploadKanbanView = {
    ...fileUploadKanbanView,
    Controller: SaleFileUploadKanbanController,
    Renderer: SaleFileUploadKanbanRenderer,
};

registry.category("views").add("sale_file_upload_kanban", saleFileUploadKanbanView);
