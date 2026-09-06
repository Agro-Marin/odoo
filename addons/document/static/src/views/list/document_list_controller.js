/** @odoo-module native */
import { Dropdown } from "@web/components/dropdown";
import { ListController } from "@web/views/list";
import { DocumentsControllerMixin } from "@document/views/document_controller_mixin";
import { DocumentsSelectionBox } from "@document/views/selection_box/document_selection_box";

export class DocumentsListController extends DocumentsControllerMixin(ListController) {
    static template = "document.DocumentsListController";
    static components = {
        ...ListController.components,
        Dropdown,
        SelectionBox: DocumentsSelectionBox,
    };
    static selectedDocumentsSelector =
        ".o_data_row.o_data_row_selected .o_list_record_selector";

    setup() {
        super.setup(...arguments);
        if (!this.documentService.userIsInternal) {
            this.archInfo.columns = this.archInfo.columns.filter(
                (col) => !this.internalOnlyColumns.includes(col.name),
            );
        }
    }

    get internalOnlyColumns() {
        return ["company_id"];
    }
}
