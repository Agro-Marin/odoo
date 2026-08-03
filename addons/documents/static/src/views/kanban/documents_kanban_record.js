/** @odoo-module native */
import { _t } from "@web/core/translation";
import { KanbanRecord } from "@web/views/kanban";
import { FileUploadProgressBar } from "@web/components/file_upload";
import { useBus, useService } from "@web/core/utils/hooks";
import { useEffect, useState } from "@odoo/owl";

const CANCEL_GLOBAL_CLICK = ["a", ".dropdown", ".oe_kanban_action"].join(",");

export class DocumentsKanbanRecord extends KanbanRecord {
    static components = {
        ...KanbanRecord.components,
        FileUploadProgressBar,
    };
    static defaultProps = {
        ...KanbanRecord.defaultProps,
    };
    static props = [...KanbanRecord.props];
    static template = "documents.DocumentsKanbanRecord";

    setup() {
        super.setup();
        // File upload
        const { bus, uploads } = useService("file_upload");
        this.documentUploads = uploads;
        useBus(bus, "FILE_UPLOAD_ADDED", (ev) => {
            // `Number()`, because `FormData.get()` always answers a string while
            // `resId` is a number.
            if (Number(ev.detail.upload.data.get("document_id")) === this.props.record.resId) {
                this.render(true);
            }
        });

        this.documentService = useService("document.document");
        this.thumbnailService = useService("documents_client_thumbnail");
        this.thumbnailService.enqueueRecords([this.props.record]);
        this.contentState = useState({ documentEmailContent: null });
        useEffect(
            () => {
                this.fetchDocumentsEmailContent();
            },
            () => [this.props.record?.data.attachment_id?.id]
        );

        // Activity updates from Chatter
        useBus(this.documentService.bus, "DOCUMENT_CHATTER_ACTIVITY_CHANGED", ({ detail }) => {
            if (this.props.record.data.id === detail.recordId) {
                this.props.record.load();
            }
        });
    }

    /**
     * @override
     */
    getRecordClasses() {
        let result = super.getRecordClasses();
        if (this.props.record.selected) {
            result += " o_record_selected";
        }
        if (this.props.record.isRequest()) {
            result += " oe_file_request";
        }
        if (this.props.record.data.type === "folder") {
            result += " o_folder_record";
        }
        if (
            this.env.isSmall &&
            this.props.groupByField?.name === "last_access_date_group"
        ) {
            result += " flex-grow-1";
        }
        return result;
    }

    get renderingContext() {
        const context = super.renderingContext;
        context.encodeURIComponent = encodeURIComponent;

        if ([false, "TRASH", "RECENT"].includes(this.env.searchModel.getSelectedFolderId())) {
            context.inFolder =
                this.props.record.data.folder_id?.display_name ||
                {
                    MY: _t("My Drive"),
                    COMPANY: _t("Company"),
                    SHARED: _t("Shared with me"),
                }[this.props.record.data.user_folder_id];
        }
        context.mimetype = this.props.record.shortcutTarget.data.mimetype;
        context.documentEmailContent = this.contentState.documentEmailContent;
        return context;
    }
    /**
     * Get the current file upload for this record if there is any
     */
    getFileUpload() {
        return Object.values(this.documentUploads).find(
            (upload) =>
                Number(upload.data.get("document_id")) === this.props.record.resId
        );
    }

    /**
     * @override
     */
    onGlobalClick(ev) {
        if (ev.target.closest(CANCEL_GLOBAL_CLICK)) {
            return;
        }
        const selectionLength = this.props.getSelection().length;
        // We can enable selection mode when only one item is selected if a key is pressed,
        // or if we have more than one item selected
        const isSelectionModeActive = selectionLength === 1 ? ev.shiftKey : selectionLength > 1;
        const selectionKeyActive = ev.altKey || ev.ctrlKey;
        if (
            ev.target.closest("div[name='document_preview']") &&
            !(selectionKeyActive || ev.shiftKey)
        ) {
            this.props.record.onClickPreview(ev);
        } else if (selectionKeyActive || isSelectionModeActive) {
            this.rootRef.el.focus();
            this.props.toggleSelection(this.props.record, ev.shiftKey);
        } else if (
            this.env.searchModel.getSelectedFolderId() === "TRASH" ||
            this.props.record.data.type !== "folder"
        ) {
            // Select only one document record
            this.props.getSelection().forEach((r) => r.toggleSelection(false));
            this.rootRef.el.focus();
            this.props.toggleSelection(this.props.record);
        } else {
            this.props.record.openFolder();
        }
    }

    async fetchDocumentsEmailContent() {
        const target = this.props.record.shortcutTarget;
        if (target.data.mimetype !== "application/documents-email") {
            return;
        }
        // The thumbnail is decoration: a body that fails to load leaves the card
        // showing the watermark rather than raising at the user.
        try {
            this.contentState.documentEmailContent =
                await this.documentService.loadEmailContent(target.resId);
        } catch {
            this.contentState.documentEmailContent = null;
        }
    }
}
