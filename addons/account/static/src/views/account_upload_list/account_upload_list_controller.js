/** @odoo-module native */
import { FileUploadListController } from "../file_upload_list/file_upload_list_controller.js";
import { AccountFileUploader } from "../../components/account_file_uploader/account_file_uploader.js";

export class AccountUploadListController extends FileUploadListController {
    static components = {
        ...FileUploadListController.components,
        AccountFileUploader,
    };
}
