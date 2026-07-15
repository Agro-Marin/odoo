/** @odoo-module native */
import { FileUploadKanbanController } from "../file_upload_kanban/file_upload_kanban_controller.js";
import { WithAccountFileUploader, showAccountUploadButton } from "../account_file_uploader_mixin.js";

export class AccountMoveKanbanController extends WithAccountFileUploader(FileUploadKanbanController) {
    setup() {
        super.setup();
        this.showUploadButton = showAccountUploadButton(this.props.context);
    }
}
