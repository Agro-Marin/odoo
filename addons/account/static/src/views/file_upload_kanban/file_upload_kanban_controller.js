/** @odoo-module native */
import { DocumentFileUploader } from "@account/components/document_file_uploader/document_file_uploader";
import { KanbanController } from "@web/views/kanban/kanban_controller";

export class FileUploadKanbanController extends KanbanController {
    static components = {
        ...KanbanController.components,
        DocumentFileUploader,
    };
}
