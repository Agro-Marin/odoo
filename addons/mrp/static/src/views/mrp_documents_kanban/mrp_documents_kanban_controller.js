/** @odoo-module native */
import { ProductDocumentKanbanController } from "@product/js/product_document_kanban/product_document_kanban_controller";
import { patch } from "@web/core/utils/patch";

patch(ProductDocumentKanbanController.prototype, {
    setup() {
        super.setup(...arguments);
        if (this.props.context.attached_on_bom) {
            this.formData.attached_on_bom = this.props.context.bom_id;
        }
    },
});
