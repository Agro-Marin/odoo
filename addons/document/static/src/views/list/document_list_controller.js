/** @odoo-module native */
import { Dropdown } from "@web/components/dropdown";
import { useService } from "@web/core/utils/hooks";
import { ListController } from "@web/views/list";
import { DocumentsControllerMixin } from "@document/views/document_controller_mixin";
import { preSuperSetup, useDocumentView } from "@document/views/hooks";
import { DocumentsSelectionBox } from "@document/views/selection_box/document_selection_box";
import { onWillDestroy, onWillRender, useRef, useState } from "@odoo/owl";

export class DocumentsListController extends DocumentsControllerMixin(ListController) {
    static template = "document.DocumentsListController";
    static components = {
        ...ListController.components,
        Dropdown,
        SelectionBox: DocumentsSelectionBox,
    };
    setup() {
        preSuperSetup();
        super.setup(...arguments);
        this.documentService = useService("document.document");
        this.uploadFileInputRef = useRef("uploadFileInput");
        const properties = useDocumentView(this.documentsViewHelpers());
        Object.assign(this, properties);

        this.documentStates = useState({
            previewStore: {},
        });
        this.rightPanelState = useState(this.documentService.rightPanelReactive);

        if (!this.documentService.userIsInternal) {
            this.archInfo.columns = this.archInfo.columns.filter(
                (col) => !this.internalOnlyColumns.includes(col.name),
            );
        }

        // Registered synchronously: the control panel's DocumentsAction reads
        // it from its own mounted effect, which runs before this component's.
        const getSelectionActions = () => ({
            getTopbarActions: () => this.getTopBarActionMenuItems(),
            getMenuProps: () => this.actionMenuProps,
        });
        this.documentService.getSelectionActions = getSelectionActions;
        onWillDestroy(() => {
            // On a view switch the next controller has already registered its own.
            if (this.documentService.getSelectionActions === getSelectionActions) {
                this.documentService.getSelectionActions = null;
            }
        });

        onWillRender(() => this.openInitialPreview());
    }

    get hasSelectedRecords() {
        return this.targetRecords.length;
    }

    get targetRecords() {
        return this.model.targetRecords;
    }

    get internalOnlyColumns() {
        return ["company_id"];
    }

    documentsViewHelpers() {
        return {
            getSelectedDocumentsElements: () =>
                this.root?.el?.querySelectorAll(
                    ".o_data_row.o_data_row_selected .o_list_record_selector",
                ) || [],
            setPreviewStore: (previewStore) => {
                this.documentStates.previewStore = previewStore;
            },
            isRecordPreviewable: this.isRecordPreviewable.bind(this),
        };
    }

    isRecordPreviewable(record) {
        return record.isViewable();
    }
}
