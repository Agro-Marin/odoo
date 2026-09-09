/** @odoo-module native */
import { registry } from "@web/core/registry";

import { kanbanView } from "@web/views/kanban";
import { AccountReturnCheckKanbanRenderer } from "./account_return_check_kanban_renderer.js";
import { AccountReturnCheckKanbanController } from "./account_return_check_kanban_controller.js";
import { AccountReturnCheckControlPanel } from "./account_return_check_control_panel.js";

export const accountReturnCheckKanbanView = {
    ...kanbanView,
    Renderer: AccountReturnCheckKanbanRenderer,
    Controller: AccountReturnCheckKanbanController,
    ControlPanel: AccountReturnCheckControlPanel,
};

registry
    .category("views")
    .add("account_return_check_kanban", accountReturnCheckKanbanView);
