/** @odoo-module native */
import { DocumentFileUploader } from "@account/components/document_file_uploader/document_file_uploader";
import { ListController } from "@web/views/list";

export class FileUploadListController extends ListController {
    static components = {
        ...ListController.components,
        DocumentFileUploader,
    };
}
