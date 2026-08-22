/** @odoo-module native */
import { WithAccountFileUploader } from "../account_file_uploader_mixin.js";
import { FileUploadKanbanController } from "../file_upload_kanban/file_upload_kanban_controller.js";

export class AccountMoveKanbanController extends WithAccountFileUploader(
    FileUploadKanbanController,
) {}
