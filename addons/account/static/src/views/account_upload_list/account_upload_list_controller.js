/** @odoo-module native */
import { WithAccountFileUploader } from "../account_file_uploader_mixin.js";
import { FileUploadListController } from "../file_upload_list/file_upload_list_controller.js";

export class AccountUploadListController extends WithAccountFileUploader(
    FileUploadListController,
) {}
