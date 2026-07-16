/** @odoo-module native */
import { registry } from "@web/core/registry";

import { fileUploadKanbanView } from "../file_upload_kanban/file_upload_kanban_view.js";
import { AccountMoveKanbanController } from "./account_move_kanban_controller.js";

export const accountMoveUploadKanbanView = {
    ...fileUploadKanbanView,
    Controller: AccountMoveKanbanController,
    buttonTemplate: "account.AccountMoveKanbanView.Buttons",
};

registry.category("views").add("account_documents_kanban", accountMoveUploadKanbanView);
