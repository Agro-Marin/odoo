/** @odoo-module native */
import { FileUploadListController } from "@account/views/file_upload_list/file_upload_list_controller";
import { FileUploadListRenderer } from "@account/views/file_upload_list/file_upload_list_renderer";
import { fileUploadListView } from "@account/views/file_upload_list/file_upload_list_view";
import { PurchaseFileUploader } from "@purchase/components/purchase_file_uploader/purchase_file_uploader";
import { PurchaseDashBoard } from "@purchase/views/purchase_dashboard";
import { useDebugMode } from "@web/core/debug/debug_context";
import { useDialogContext } from "@web/core/dialog_context_hooks";
import { registry } from "@web/core/registry";
import { useService } from "@web/core/utils/hooks";

export class PurchaseDashBoardRenderer extends FileUploadListRenderer {
    static template = "purchase.ListRenderer";
    static components = { ...FileUploadListRenderer.components, PurchaseDashBoard };

    setup() {
        super.setup();
        this.debug = useDebugMode();
    }
}

export class PurchaseFileUploadListController extends FileUploadListController {
    static template = `purchase.ListView`;
    static components = {
        ...FileUploadListController.components,
        PurchaseFileUploader,
    };

    setup() {
        super.setup();
        this.dialogContext = useDialogContext();
        this.ui = useService("ui");
    }
}

export const PurchaseDashBoardListView = {
    ...fileUploadListView,
    Controller: PurchaseFileUploadListController,
    Renderer: PurchaseDashBoardRenderer,
};

registry.category("views").add("purchase_dashboard_list", PurchaseDashBoardListView);
