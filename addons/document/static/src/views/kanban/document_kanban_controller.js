/** @odoo-module native */
import { DocumentsControllerMixin } from "@document/views/document_controller_mixin";
import { DocumentsSelectionBox } from "@document/views/selection_box/document_selection_box";
import { KanbanController } from "@web/views/kanban";
import { Dropdown } from "@web/components/dropdown";
import { useService } from "@web/core/utils/hooks";
import { useSearchModel } from "@web/search/search_model";

export class DocumentsKanbanController extends DocumentsControllerMixin(
    KanbanController,
) {
    static template = "document.DocumentsKanbanView";
    static components = {
        ...KanbanController.components,
        Dropdown,
        SelectionBox: DocumentsSelectionBox,
    };
    static selectedDocumentsSelector = ".o_kanban_record.o_record_selected";

    setup() {
        super.setup();
        this.searchModel = useSearchModel();
        this.ui = useService("ui");
    }

    onUnselectAll() {
        this.model.root.selection.forEach((record) => {
            record.toggleSelection(false);
        });
        this.model.root.selectDomain(false);
    }

    async onSelectDomain() {
        await this.model.root.selectDomain(true);
    }
}
