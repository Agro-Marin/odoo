/** @odoo-module native */
import { browser } from "@web/core/browser/browser";
import { ConfirmationDialog } from "@web/ui/dialog";
import { Domain } from "@web/core/domain";
import { _t } from "@web/core/translation";
import { user } from "@web/core/user";
import { useService } from "@web/core/utils/hooks";
import { getCommonEmbeddedActions } from "@documents/views/utils";
import { getSpecEvalContext } from "@web/model/relational_model";

export const DocumentsModelMixin = (component) =>
    class extends component {
        setup(params) {
            super.setup(...arguments);
            if (this.config.resModel === "documents.document") {
                this.originalSelection = params.state?.sharedSelection;
            }
            this.action = useService("action");
            this.dialogService = useService("dialog");
            this.documentService = useService("document.document");
            this.notification = useService("notification");
        }

        exportSelection() {
            return this.targetRecords.map((rec) => rec.resId);
        }

        /**
         * @override
         */
        async load(params = {}) {
            const selection = this.root?.selection;
            if (this.originalSelection === undefined && selection && selection.length > 0) {
                this.originalSelection = selection.map((rec) => rec.resId);
            }
            const nextParams =
                this.config.resModel === "documents.document"
                    ? {
                          ...params,
                          context: {
                              ...(params.context ?? this.config.context),
                              skip_res_field_check: true,
                          },
                      }
                    : params;
            const res = await super.load(nextParams);
            if (this.config.resModel !== "documents.document") {
                return res;
            }
            this.env.searchModel.skipLoadClosePreview
                ? (this.env.searchModel.skipLoadClosePreview = false)
                : this.env.documentsView.bus.trigger("documents-close-preview");
            this._reapplySelection();
            this._computeFileSize();
            this.shortcutTargetRecords = this.orm.isSample
                ? []
                : await this._loadShortcutTargetRecords();
            this.documentIdToRestore = undefined;
            return res;
        }

        _reapplySelection() {
            const records = this.root.records;
            if (!records) {
                return;
            }
            if (this.originalSelection?.length) {
                const originalSelection = new Set(this.originalSelection);
                records.forEach((record) => {
                    record.selected = originalSelection.has(record.resId);
                });
            }
            delete this.originalSelection;
        }

        _computeFileSize() {
            let size = 0;
            if (this.root.groups) {
                size = this.root.groups.reduce(
                    (size, group) => size + group.aggregates.file_size,
                    0
                );
            } else if (this.root.records) {
                size = this.root.records.reduce((size, rec) => size + rec.data.file_size, 0);
            }
            size /= 1000 * 1000;
            this.fileSize = Math.round(size * 100) / 100;
        }

        async _loadShortcutTargetRecords() {
            const shortcuts = this.root.records.filter(
                (record) => !!record.data.shortcut_document_id
            );
            if (!shortcuts.length) {
                return [];
            }
            const shortcutTargetRecords = [];
            const targetRecords = await this._loadRecords(
                {
                    ...this.config,
                    resIds: shortcuts.map(
                        (record) => record.data.shortcut_document_id.id,
                    ),
                },
                getSpecEvalContext(this.config),
            );
            for (const targetRecord of targetRecords) {
                shortcutTargetRecords.push(this._createRecordDatapoint(targetRecord));
            }
            return shortcutTargetRecords;
        }

        _createRecordDatapoint(data, mode = "readonly") {
            return new this.constructor.Record(
                this,
                {
                    context: this.config.context,
                    activeFields: this.config.activeFields,
                    resModel: this.config.resModel,
                    fields: this.config.fields,
                    resId: data.id || false,
                    resIds: data.id ? [data.id] : [],
                    isMonoRecord: true,
                    mode,
                },
                data,
                { manuallyAdded: !data.id }
            );
        }

        async _notifyChange() {
            await this.load();
            await this.notify();
            await this.env.searchModel._reloadSearchModel(true);
            this.documentService.setPreviewedDocument(null);
        }

        get isDomainSelected() {
            return this.root.isDomainSelected && !this.documentService.rightPanelReactive.previewedDocument;
        }

        getResIds(extraDomain) {
            if (extraDomain) {
                const newDomain = Domain.and([this.root.domain, extraDomain]).toList();
                return this.orm.search("documents.document", newDomain, {
                    limit: this.activeIdsLimit,
                    context: this.root.context,
                });
            }
            return this.root.getResIds(true);
        }

        get targetRecords() {
            return this.documentService.rightPanelReactive.previewedDocument
                ? [this.documentService.rightPanelReactive.previewedDocument.record]
                : this.root.selection;
        }

        get canManageVersions() {
            if (this.targetRecords.length !== 1) {
                return false;
            }
            const singleSelection = this.targetRecords[0];
            const currentFolder = this.env.searchModel.getSelectedFolder();
            return (
                this.documentService.userIsInternal &&
                singleSelection &&
                currentFolder?.id !== "TRASH" &&
                singleSelection.data.type === "binary" &&
                singleSelection.data.attachment_id &&
                !singleSelection.data.lock_uid
            );
        }

        get canDeleteRecords() {
            const documents = this.targetRecords.map((r) => r.data);
            if (this.documentService.userIsInternal) {
                return documents.some((d) => !d.active);
            }
            return documents.every(
                (r) =>
                    r.owner_id?.id === user.userId &&
                    ["binary", "url"].includes(r.type) &&
                    typeof r.folder_id?.id === "number" &&
                    this.env.searchModel.getFolderById(r.folder_id.id).user_permission === "edit"
            );
        }

        get canDuplicateRecords() {
            return (
                this.documentService.hasFolderEditorAccess &&
                this.targetRecords.every((r) => !r.data.lock_uid && r.data.active)
            );
        }

        get canMoveRecords() {
            return (
                this.documentService.hasFolderEditorAccess &&
                this.targetRecords.some((r) => r.data.user_can_move)
            );
        }

        async onCopyLinks() {
            const urls = this.isDomainSelected
                ? (
                      await this.orm.read(
                          "documents.document",
                          await this.getResIds(),
                          ["access_url"]
                      )
                  ).map((d) => d.access_url)
                : this.targetRecords.map((d) => d.data.access_url);
            const linksToShare = urls.length > 1 ? urls.join(", ") : urls[0];

            await browser.navigator.clipboard.writeText(linksToShare);
            const message =
                urls.length > 1
                    ? _t("Links copied to clipboard!")
                    : _t("Link copied to clipboard!");
            this.notification.add(message, { type: "success" });
        }

        async onToggleLock() {
            if (this.targetRecords.length !== 1) {
                return;
            }
            const record = this.targetRecords[0];
            if (record.data.lock_uid && record.data.lock_uid.id !== user.userId) {
                this.dialogService.add(ConfirmationDialog, {
                    title: _t("Warning"),
                    body: _t(
                        "This document is locked by %s.\nAre you sure you want to unlock it?",
                        record.data.lock_uid.display_name
                    ),
                    confirmLabel: _t("Unlock"),
                    confirm: async () => {
                        await this.orm.call("documents.document", "toggle_lock", [record.data.id]);
                        await this._notifyChange();
                    },
                    cancelLabel: _t("Discard"),
                    cancel: () => {},
                });
            } else {
                await this.orm.call("documents.document", "toggle_lock", [record.data.id]);
                await this._notifyChange();
            }
        }

        async onToggleRightPanel() {
            await this.documentService.toggleRightPanelVisibility();
        }

        async onCreateShortcut() {
            const documents = this.targetRecords;
            await this.documentService.openOperationDialog({
                documents: this.isDomainSelected
                    ? (await this.getResIds()).map((d) => ({ id: d }))
                    : documents.map((d) => ({
                          id: d.data.id,
                          name: d.data.name,
                      })),
                operation: "shortcut",
                onClose: async () => this._notifyChange(),
            });
        }

        async onDelete() {
            const records = this.isDomainSelected
                ? null
                : this.documentService.userIsInternal
                  ? this.targetRecords.filter((r) => !r.data.active)
                  : this.targetRecords;
            if (records && !records.length) {
                return;
            }
            const confirmed = await new Promise((resolve) => {
                const dialogProps = {
                    title: _t("Delete permanently"),
                    body:
                        this.root.isDomainSelected || this.root.selection.length > 1
                            ? _t(
                                  "Are you sure you want to permanently erase the selected documents?"
                              )
                            : _t(
                                  "Are you sure you want to permanently erase the selected document?"
                              ),
                    confirmLabel: _t("Delete permanently"),
                    cancelLabel: _t("Discard"),
                    confirm: async () => resolve(true),
                    cancel: () => resolve(false),
                };
                this.dialogService.add(ConfirmationDialog, dialogProps);
            });
            if (!confirmed) {
                return;
            }
            if (records) {
                await this.root.deleteRecords(records);
            } else {
                const resIds = !this.documentService.userIsInternal
                    ? await this.getResIds()
                    : await this.getResIds([["active", "=", false]]);
                await this.orm.unlink("documents.document", resIds, {
                    context: this.root.context,
                });
            }
            await this._notifyChange();
        }

        async onArchive() {
            const records = this.targetRecords.filter((r) => r.data.active && !r.data.lock_uid);
            const recordIds = this.isDomainSelected
                ? await this.getResIds([["lock_uid", "=", false]])
                : records.map((rec) => rec.data.id);
            if (await this.documentService.moveToTrash(recordIds)) {
                await this._notifyChange();
            }
        }

        async onDuplicate() {
            const documents = this.targetRecords;
            await this.documentService.openOperationDialog({
                documents: this.isDomainSelected
                    ? (await this.getResIds()).map((d) => ({ id: d }))
                    : documents.map((d) => ({
                          id: d.data.id,
                          name: d.data.name,
                      })),
                operation: "copy",
                onClose: async () => this.env.searchModel._reloadSearchModel(true),
            });
        }

        async onManageVersions() {
            await this.documentService.openDialogManageVersions(this.targetRecords[0].data.id);
        }

        async onRestore() {
            const records = this.targetRecords.filter((r) => !r.data.active);
            const recordIds = this.isDomainSelected
                ? await this.getResIds([["active", "=", false]])
                : records.map((r) => r.data.id);
            await this.orm.call("documents.document", "action_unarchive", [recordIds]);
            await this.env.searchModel._reloadSearchModel(true);
        }

        onSplitPDF() {
            const documents = this.targetRecords;
            if (!documents?.length || !documents.every((d) => d.isPdf())) {
                return;
            }

            this.env.documentsView.bus.trigger("documents-open-preview", {
                documents: documents,
                mainDocument: this.targetRecords[0],
                isPdfSplit: true,
                embeddedActions: getCommonEmbeddedActions(documents),
            });
        }

        async onRename() {
            if (this.targetRecords.length !== 1) {
                return;
            }
            await this.documentService.openDialogRename(this.targetRecords[0].data.id);
            await this._notifyChange();
        }

        async onShare() {
            const documentIds = this.isDomainSelected
                ? await this.getResIds()
                : this.targetRecords.map((d) => d.data.id);
            await this.documentService.openSharingDialog(documentIds);
        }

        async onMove() {
            const documents = this.targetRecords.filter((r) => r.data.user_can_move);
            await this.documentService.openOperationDialog({
                documents: this.isDomainSelected
                    ? (await this.getResIds()).map((d) => ({ id: d }))
                    : documents.map((d) => ({
                          id: d.data.id,
                          name: d.data.name,
                      })),
                operation: "move",
                onClose: async () => this.env.searchModel._reloadSearchModel(true),
            });
        }

        async onDoAction(actionId) {
            const documentIds = this.isDomainSelected
                ? await this.getResIds()
                : this.targetRecords.map((record) => record.data.id);

            const context = {
                active_model: "documents.document",
                active_ids: documentIds,
            };
            const action = await this.orm.call(
                "documents.document",
                "action_execute_embedded_action",
                [actionId],
                { context }
            );
            if (action) {
                await this.action.doAction(action, {
                    onClose: () => {
                        this._notifyChange();
                    },
                });
                if (action.tag !== "display_notification") {
                    return;
                }
            }
            await this._notifyChange();
        }

        async onDownload() {
            if (this.isDomainSelected) {
                const domain = Domain.and([
                    [["type", "!=", "url"]],
                    Domain.or([
                        [["type", "=", "folder"]],
                        [["attachment_id", "!=", false]],
                        [["shortcut_document_id.attachment_id", "!=", false]],
                    ]),
                ]);
                const resIds = await this.getResIds(domain);
                this.documentService.downloadDocuments(this.targetRecords, resIds);
            } else {
                this.documentService.downloadDocuments(this.targetRecords);
            }
        }
        async _loadDocumentToRestore(config, data) {
            const documentIdToRestore = this.documentService.getOnceDocumentIdToRestore();
            if (!documentIdToRestore) {
                return;
            }
            const idxToRestore = data.records.findIndex((r) => r.id === documentIdToRestore);
            if (idxToRestore !== -1) {
                const recordToRestore = data.records.splice(idxToRestore, 1)[0];
                data.records.splice(0, 0, recordToRestore);
                this.documentIdToRestore = documentIdToRestore;
            } else {
                const missingData = await super._loadData({
                    ...config,
                    domain: Domain.and([
                        config.domain,
                        [["id", "=", documentIdToRestore]],
                    ]).toList(),
                    limit: 1,
                });
                if (missingData?.records?.length) {
                    data.records.splice(0, 0, missingData.records[0]);
                    data.records.pop();
                    this.documentIdToRestore = documentIdToRestore;
                } else {
                    this.notification.add(_t("Document not found or inaccessible."), {
                        type: "danger",
                    });
                }
            }
        }
    };
