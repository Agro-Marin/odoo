/** @odoo-module native */
import { ProductDocumentKanbanRecord } from "@product/js/product_document_kanban/product_document_kanban_record";
import {
    FileUploadProgressContainer,
    FileUploadProgressKanbanRecord,
} from "@web/components/file_upload";
import { useService } from "@web/core/utils/hooks";
import { KanbanRenderer } from "@web/views/kanban";

export class ProductDocumentKanbanRenderer extends KanbanRenderer {
    static components = {
        ...KanbanRenderer.components,
        FileUploadProgressContainer,
        FileUploadProgressKanbanRecord,
        KanbanRecord: ProductDocumentKanbanRecord,
    };
    static template = "product.ProductDocumentKanbanRenderer";
    setup() {
        super.setup();
        this.fileUploadService = useService("file_upload");
    }
}
