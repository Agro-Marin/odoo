/** @odoo-module native */
import { registry } from "@web/core/registry";

import { ExpenseDashboard } from "../components/expense_dashboard.js";
import { ExpenseMobileQRCode } from "../mixins/qrcode.js";
import {
    ExpenseDocumentUpload,
    ExpenseDocumentDropZone,
} from "../mixins/document_upload.js";

import { kanbanView, KanbanController, KanbanRenderer } from "@web/views/kanban";
import { useService } from "@web/core/utils/hooks";

export class ExpenseKanbanController extends ExpenseDocumentUpload(KanbanController) {
    static template = "hr_expense.KanbanView";

    setup() {
        super.setup();
        this.ui = useService("ui");
    }
}

export class ExpenseKanbanRenderer extends ExpenseDocumentDropZone(
    ExpenseMobileQRCode(KanbanRenderer),
) {
    static template = "hr_expense.KanbanRenderer";

    setup() {
        super.setup();
        this.ui = useService("ui");
    }
}

export class ExpenseDashboardKanbanRenderer extends ExpenseKanbanRenderer {
    static components = {
        ...ExpenseDashboardKanbanRenderer.components,
        ExpenseDashboard,
    };
    static template = "hr_expense.DashboardKanbanRenderer";

    setup() {
        super.setup();
        this.ui = useService("ui");
    }
}

registry.category("views").add("hr_expense_kanban", {
    ...kanbanView,
    Controller: ExpenseKanbanController,
    Renderer: ExpenseKanbanRenderer,
});

registry.category("views").add("hr_expense_dashboard_kanban", {
    ...kanbanView,
    Controller: ExpenseKanbanController,
    Renderer: ExpenseDashboardKanbanRenderer,
});
