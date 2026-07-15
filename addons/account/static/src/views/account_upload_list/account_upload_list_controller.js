/** @odoo-module native */
import { FileUploadListController } from "../file_upload_list/file_upload_list_controller.js";
import { WithAccountFileUploader } from "../account_file_uploader_mixin.js";

export class AccountUploadListController extends WithAccountFileUploader(FileUploadListController) {}
