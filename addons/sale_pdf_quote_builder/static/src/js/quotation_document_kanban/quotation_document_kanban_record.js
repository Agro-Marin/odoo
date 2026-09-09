/** @odoo-module native */
import { ProductDocumentKanbanRecord } from "@product/js/product_document_kanban/product_document_kanban_record";

export class QuotationDocumentKanbanRecord extends ProductDocumentKanbanRecord {
    /** @override */
    get attachment() {
        return this.props.record.data.ir_attachment_id;
    }
}
