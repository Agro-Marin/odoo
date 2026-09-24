/** @odoo-module native */
import { FileUploadKanbanRenderer } from "@account/views/file_upload_kanban/file_upload_kanban_renderer";
import { fileUploadKanbanView } from "@account/views/file_upload_kanban/file_upload_kanban_view";
import { PurchaseDashBoard } from "@purchase/views/purchase_dashboard";
import { registry } from "@web/core/registry";
import { useService } from "@web/core/utils/hooks";

export class PurchaseDashBoardKanbanRenderer extends FileUploadKanbanRenderer {
    static template = "purchase.PurchaseKanbanView";
    static components = { ...FileUploadKanbanRenderer.components, PurchaseDashBoard };

    setup() {
        super.setup();
        this.ui = useService("ui");
    }
}

export const PurchaseDashBoardKanbanView = {
    ...fileUploadKanbanView,
    Renderer: PurchaseDashBoardKanbanRenderer,
};

registry
    .category("views")
    .add("purchase_dashboard_kanban", PurchaseDashBoardKanbanView);
