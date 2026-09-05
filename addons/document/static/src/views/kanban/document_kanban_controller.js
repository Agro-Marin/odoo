/** @odoo-module native */
import { preSuperSetup, useDocumentView } from "@document/views/hooks";
import { DocumentsControllerMixin } from "@document/views/document_controller_mixin";
import { DocumentsSelectionBox } from "@document/views/selection_box/document_selection_box";
import { onWillRender, useEffect, useRef, useState } from "@odoo/owl";
import { KanbanController } from "@web/views/kanban";
import { Dropdown } from "@web/components/dropdown";

export class DocumentsKanbanController extends DocumentsControllerMixin(
    KanbanController,
) {
    static template = "document.DocumentsKanbanView";
    static components = {
        ...KanbanController.components,
        Dropdown,
        SelectionBox: DocumentsSelectionBox,
    };
    setup() {
        preSuperSetup();
        super.setup(...arguments);
        this.uploadFileInputRef = useRef("uploadFileInput");
        const properties = useDocumentView(this.documentsViewHelpers());
        Object.assign(this, properties);

        this.documentStates = useState({
            previewStore: {},
        });
        this.rightPanelState = useState(this.documentService.rightPanelReactive);

        useEffect(
            () => {
                this.documentService.getSelectionActions = () => ({
                    getTopbarActions: () => this.getTopBarActionMenuItems(),
                    getMenuProps: () => this.actionMenuProps,
                });
            },
            () => [],
        );

        onWillRender(() => this.openInitialPreview());
    }

    get hasSelectedRecords() {
        return this.targetRecords.length;
    }

    get targetRecords() {
        return this.model.targetRecords;
    }

    documentsViewHelpers() {
        return {
            getSelectedDocumentsElements: () =>
                this.root?.el?.querySelectorAll(".o_kanban_record.o_record_selected") ||
                [],
            setPreviewStore: (previewStore) => {
                this.documentStates.previewStore = previewStore;
            },
            isRecordPreviewable: this.isRecordPreviewable.bind(this),
        };
    }

    isRecordPreviewable(record) {
        return record.isViewable();
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
