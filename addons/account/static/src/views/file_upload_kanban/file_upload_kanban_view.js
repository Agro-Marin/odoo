/** @odoo-module native */
import { registry } from "@web/core/registry";
import { kanbanView } from "@web/views/kanban/kanban_view";

import { FileUploadKanbanController } from "./file_upload_kanban_controller.js";
import { FileUploadKanbanRenderer } from "./file_upload_kanban_renderer.js";

export const fileUploadKanbanView = {
    ...kanbanView,
    Controller: FileUploadKanbanController,
    Renderer: FileUploadKanbanRenderer,
    buttonTemplate: "account.FileuploadKanbanView.Buttons",
};

registry.category("views").add("file_upload_kanban", fileUploadKanbanView);
