/** @odoo-module native */
import { useCommand } from "@web/ui/commands";
import { getActiveHotkey } from "@web/core/browser/hotkeys";
import {
    FileUploadProgressContainer,
    FileUploadProgressDataRow,
} from "@web/components/file_upload";
import { _t } from "@web/core/translation";
import { useService } from "@web/core/utils/hooks";
import { ListRenderer } from "@web/views/list";

import { DocumentsRightPanel } from "@documents/components/documents_right_panel/documents_right_panel";
import { DocumentsActionHelper } from "@documents/views/helper/documents_action_helper";
import { useDraggableDocuments } from "@documents/views/helper/documents_draggable";
import { DocumentsDropZone } from "@documents/views/helper/documents_drop_zone";
import { DocumentsFileViewer } from "@documents/views/helper/documents_file_viewer";
import { DocumentsRendererMixin } from "@documents/views/documents_renderer_mixin";

import { useRef, useState } from "@odoo/owl";

export class DocumentsSecondaryListRenderer extends ListRenderer {
    static props = [...ListRenderer.props, "previewStore"];
}

export class DocumentsListRenderer extends DocumentsRendererMixin(DocumentsSecondaryListRenderer) {
    static template = "documents.DocumentsListRenderer";
    static recordRowTemplate = "documents.DocumentsListRenderer.RecordRow";
    static components = Object.assign({}, ListRenderer.components, {
        FileUploadProgressContainer,
        FileUploadProgressDataRow,
        DocumentsDropZone,
        DocumentsActionHelper,
        DocumentsFileViewer,
        DocumentsRightPanel,
    });

    setup() {
        super.setup();
        this.root = useRef("root");
        const { uploads } = useService("file_upload");
        // See the kanban renderer: the raw service reactive subscribes nobody.
        this.documentUploads = useState(uploads);
        useCommand(
            _t("Select all"),
            () => {
                const allSelected =
                    this.props.list.selection.length === this.props.list.records.length;
                this.props.list.records.forEach((record) => {
                    record.toggleSelection(!allSelected);
                });
                const focusedRecord = this.setDefaultFocus();
                // The focused record may be the container folder (or nothing at
                // all), which is never rendered as one of our own rows: only
                // records *inside* the folder carry a data-value-id. Queried on
                // this renderer's own subtree, as the kanban counterpart does.
                this.root.el
                    ?.querySelector(
                        `.o_data_row[data-value-id="${focusedRecord?.resId}"] .o_data_cell`
                    )
                    ?.focus();
            },
            {
                category: "smart_action",
                hotkey: "control+a",
                isAvailable: () => this.props.list.records.length > 0,
            }
        );

        useDraggableDocuments({
            ref: this.root,
            model: this.env.model,
            targetSelector: ".o_data_row.o_folder_record",
            elements: ".o_data_row",
            preventDrag: () =>
                this.env.searchModel.getSelectedFolderId() === "TRASH" ||
                this.getIsDomainSelected(),
            onTargetPointerEnter: ({ addClass, target, isInvalid }) => {
                addClass(target, isInvalid ? "table-danger" : "table-success");
            },
            onTargetPointerLeave: ({ removeClass, target }) => {
                removeClass(target, "table-danger", "table-success");
            },
        });
    }

    getRowClass(record) {
        let classes = super.getRowClass(record);
        if (record.data.type === "folder") {
            classes += " o_folder_record";
        }
        return classes;
    }

    getDocumentsAttachmentViewerProps() {
        return { previewStore: this.props.previewStore };
    }

    /**
     * Called when a keydown event is triggered.
     */
    onGlobalKeydown(ev) {
        if ((ev.key !== "Enter" && ev.key !== " ") || this.editedRecord) {
            return;
        }
        const row = ev.target.closest(".o_data_row");
        const record = row && this.props.list.records.find((rec) => rec.id === row.dataset.id);
        if (!record) {
            return;
        }
        if (ev.key === "Enter" && record.data.type !== "folder") {
            record.onClickPreview(ev);
        }
        ev.stopPropagation();
        ev.preventDefault();
        this.toggleRecordSelection(record);
    }

    /**
     * Upon clicking on a record, opens the folder/preview the file.
     * If ctrl or shift key pressed, selects/unselects the record.
     * If the column is editable, the record is selected and click
     * without ctrl or shift pressed, edits the column.
     */
    onCellClicked(record, column, ev) {
        ev.stopPropagation();
        const isIcon = ev.target.closest(".o_field_documents_type_icon");
        if (ev.ctrlKey || ev.metaKey || ev.shiftKey || ev.altKey) {
            this.toggleRecordSelection(record, ev);
            return;
        }
        if (isIcon) {
            if (record.data.type === "folder") {
                record.openFolder();
            } else {
                record.onClickPreview(ev);
            }
            return;
        }
        this.documentService.focusRecord(record);
        if (record.selected && this.editableColumns.includes(column.name)) {
            super.onCellClicked(...arguments);
        }
    }

    get editableColumns() {
        return ["name", "tag_ids", "partner_id", "owner_id", "company_id", "folder_id"];
    }

    /**
     * Called when a click event is triggered.
     */
    onGlobalClick(ev) {
        // NB: this intentionally does NOT leave edit mode on a background click.
        // The documents list keeps an in-progress inline edition open when the
        // user clicks the renderer background (deselect only), offering an
        // explicit discard button instead — see the "Required document name"
        // test. Adding leaveEditMode() here would discard the edit and break that.
        // We have to check that we are indeed clicking in the list view as on mobile,
        // the inspector renders above the renderer but it still triggers this event.
        if (ev.target.closest(".o_data_row") || !ev.target.closest(".o_list_renderer")) {
            return;
        }
        if (ev.target.closest(".o_documents_view thead")) {
            return; // We then have to check that we are not clicking on the header
        }
        this.documentService.focusRecord(this.getContainerRecord());
        this.props.list.selection.forEach((el) => el.toggleSelection(false));
    }

    getFolderInfo() {
        return {
            count: this.props.list.count,
            fileSize: this.props.list.model.fileSize,
        };
    }

    /**
     * @override to update focusedRecord when navigating with arrow keys
     */
    findFocusFutureCell(cell, cellIsInGroupRow, direction) {
        const futureCell = super.findFocusFutureCell(cell, cellIsInGroupRow, direction);
        if (futureCell) {
            const dataPointId = futureCell.closest("tr").dataset.id;
            const record = this.props.list.records.filter((x) => x.id === dataPointId)[0];
            if (record) {
                this.documentService.focusRecord(record);
            }
        }
        return futureCell;
    }

    onCellKeydown(ev) {
        // Enter is handled by `onGlobalKeydown`, which previews or selects.
        if (getActiveHotkey(ev) === "enter") {
            return;
        }
        return super.onCellKeydown(...arguments);
    }

    get hasSelectors() {
        return this.props.allowSelectors;
    }

    get isMobile() {
        return this.env.isSmall;
    }

    toggleRecordSelection(record) {
        const isSelection = record && !record.selected;
        super.toggleRecordSelection(record);
        if (isSelection) {
            this.documentService.focusRecord(record, true);
        }
    }

    toggleSelection() {
        super.toggleSelection();
        if (this.canSelectRecord) {
            this.setDefaultFocus();
        }
    }
}
