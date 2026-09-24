/** @odoo-module native */
import { useService } from "@web/core/utils/hooks";
import { KanbanRenderer } from "@web/views/kanban";

import { FileUploadDropzoneRendererMixin } from "../file_upload_dropzone_renderer_mixin.js";

export class FileUploadKanbanRenderer extends FileUploadDropzoneRendererMixin(
    KanbanRenderer,
) {
    static template = "account.FileUploadKanbanRenderer";

    setup() {
        super.setup();
        this.ui = useService("ui");
    }
}
