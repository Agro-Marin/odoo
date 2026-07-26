/** @odoo-module native */
import { browser } from "@web/core/browser/browser";
import { ConfirmationDialog } from "@web/ui/dialog/confirmation_dialog";
import { Domain } from "@web/core/domain";
import { _t } from "@web/core/l10n/translation";
import { user } from "@web/services/user";
import { useService } from "@web/core/utils/hooks";
import { getCommonEmbeddedActions } from "@documents/views/utils";

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
         * Also load the total file size
         * @override
         */
        async load(params = {}) {
            const selection = this.root?.selection;
            // `=== undefined`, not a truthiness test: `sharedSelection` arrives as
            // an empty array whenever the view is switched with nothing selected
            // (getGlobalState -> exportSelection -> []). `![]` is false, so a
            // truthiness test never re-captured afterwards, and `_reapplySelection`
            // only cleared the buffer when it was non-empty -- so that `[]` stuck
            // for the rest of the session and every later `load()` (i.e. every
            // rename, lock, archive, embedded action or upload, all of which go
            // through `_notifyChange`) silently wiped the user's selection.
            if (this.originalSelection === undefined && selection && selection.length > 0) {
                this.originalSelection = selection.map((rec) => rec.resId);
            }
            // The point of this block is that `load()` must not write into an
            // object it does not own.
            //
            // It used to read `for (const arg of arguments) arg.context[...] =
            // true`. The only caller that passes anything is `useModel`'s
            // `load(getSearchParams(props))`, and `params.context` there IS the
            // controller's own `props.context` object -- so the loop stamped
            // component props in place. `computeNextConfig` then copied the
            // stamped context into `this.config`, which is how every later
            // argument-less `load()` came to carry the flag too.
            //
            // On the flag itself, measured rather than assumed: it is inert for
            // this model. Every `ir.attachment._search` a documents read
            // triggers is an `[('id','in',[...])]` batch, and the `res_field`
            // guard in `ir_attachment._search` already exempts any domain
            // mentioning `id`. Related `attachment_id.*` fields resolve to a
            // LEFT JOIN, never a nested `_search`. Setting or omitting the flag
            // returns byte-identical results and the same query count.
            //
            // It is kept (upstream sets it, it costs nothing, and a future
            // domain could stop being id-scoped) but it is deliberately no
            // longer delivered by mutating props.
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
            // Consumed by now: `_loadDocumentToRestore` set it during
            // `_loadData`, and the records built from that data read it in
            // `DocumentsRecordMixin.setup` to start selected.
            this.documentIdToRestore = undefined;
            return res;
        }

        _reapplySelection() {
            const records = this.root.records;
            if (!records) {
                // Nothing to restore onto yet: keep the buffer for the next load.
                return;
            }
            if (this.originalSelection?.length) {
                const originalSelection = new Set(this.originalSelection);
                records.forEach((record) => {
                    record.selected = originalSelection.has(record.resId);
                });
            }
            // Always release the buffer, including when it was empty -- otherwise
            // an empty `sharedSelection` is never cleared and permanently blocks
            // the re-capture in `load()` above.
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
            size /= 1000 * 1000; // in MB
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
            const targetRecords = await this._loadRecords({
                ...this.config,
                resIds: shortcuts.map((record) => record.data.shortcut_document_id.id),
            });
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
            // The preview will be closed, just update the state for now
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
            // Portal user can delete their own documents while internal user can only delete document in the Trash.
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

        /**
         * Copy the links (comma-separated) of the selected documents.
         */
        async onCopyLinks() {
            // Honour a domain ("select all") selection like the other bulk
            // handlers do: reading `targetRecords` alone silently acted on the
            // records loaded in the current page, so with "All 5 selected" shown
            // the user got 2 links.
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

        /**
         * Lock / unlock the selected record.
         */
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

        /**
         * Open/Close the chatter (the info will be stored in the local storage of the current user).
         */
        async onToggleRightPanel() {
            await this.documentService.toggleRightPanelVisibility();
        }

        /**
         * Open dialog to create shortcut(s) for the selected document(s).
         */
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

        /**
         * Unlink the selected documents if they are archived.
         */
        async onDelete() {
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
            if (!this.isDomainSelected) {
                const records = !this.documentService.userIsInternal
                    ? this.targetRecords
                    : this.targetRecords.filter((r) => !r.data.active);
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

        /**
         * Send the selected documents to the trash.
         */
        async onArchive() {
            const records = this.targetRecords.filter((r) => r.data.active && !r.data.lock_uid);
            const recordIds = this.isDomainSelected
                ? await this.getResIds([["lock_uid", "=", false]])
                : records.map((rec) => rec.data.id);
            // Skip the reload (and preview close) when the user cancels the
            // confirmation dialog — moveToTrash returns false in that case.
            if (await this.documentService.moveToTrash(recordIds)) {
                await this._notifyChange();
            }
        }

        /**
         * Duplicate the selected documents.
         */
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

        /**
         * Open the "Version" modal.
         */
        async onManageVersions() {
            await this.documentService.openDialogManageVersions(this.targetRecords[0].data.id);
        }

        /**
         * Restore the selected documents.
         */
        async onRestore() {
            const records = this.targetRecords.filter((r) => !r.data.active);
            const recordIds = this.isDomainSelected
                ? await this.getResIds([["active", "=", false]])
                : records.map((r) => r.data.id);
            await this.orm.call("documents.document", "action_unarchive", [recordIds]);
            await this.env.searchModel._reloadSearchModel(true);
        }

        /**
         * Open the split / merge tool on the selected PDFs.
         */
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

        /**
         * Open the "rename" form view on the selected record.
         */
        async onRename() {
            if (this.targetRecords.length !== 1) {
                return;
            }
            await this.documentService.openDialogRename(this.targetRecords[0].data.id);
            await this._notifyChange();
        }

        /**
         * Open the permission panel of the selected document.
         */
        async onShare() {
            // Same reason as `onCopyLinks`: with a domain selection the sharing
            // dialog used to open on the loaded page only, while the UI said
            // "All N selected".
            const documentIds = this.isDomainSelected
                ? await this.getResIds()
                : this.targetRecords.map((d) => d.data.id);
            await this.documentService.openSharingDialog(documentIds);
        }

        /**
         * Open dialog to move the selected document(s).
         */
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

        /**
         * Execute the given `ir.embedded.action` on the current selected documents.
         */
        async onDoAction(actionId) {
            // Same reason: an embedded server action ran on the loaded page only
            // while the UI reported the whole domain as selected.
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
                // We might need to do a client action (e.g. to open the "Link Record" wizard)
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

        /**
         * Download the selected documents.
         */
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
        /**
         * Make sure that when coming for a specific document, it is present as the first
         * document on the first page. Notify the user if the requested document wasn't found.
         *
         * Mutates `data.records` in place and returns nothing; the callers
         * (`DocumentsListModel` / `DocumentsKanbanModel` `_loadData`) return
         * their own `data`. It used to `return data` on one branch only, which
         * read as if the result mattered.
         *
         * Hands the id to `this.documentIdToRestore` (this model) rather than to
         * the `document.document` service. It is consumed a few microtasks later
         * by `DocumentsRecordMixin.setup`, on records this very load builds, and
         * cleared at the end of `load` -- so it is load-scoped state belonging to
         * the model. On the service it was an undeclared property (the service
         * only ever declares `documentIdToRestoreOnce`) written by one mixin and
         * read by another through a process-wide singleton.
         */
        async _loadDocumentToRestore(config, data) {
            // This getter resets the DocumentIdToRestore, we'll restore it if we do have the record.
            const documentIdToRestore = this.documentService.getOnceDocumentIdToRestore();
            if (!documentIdToRestore) {
                return;
            }
            const idxToRestore = data.records.findIndex((r) => r.id === documentIdToRestore);
            if (idxToRestore !== -1) {
                const recordToRestore = data.records.splice(idxToRestore, 1)[0]; // take it out
                data.records.splice(0, 0, recordToRestore); // put it at the top of the list
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
                    data.records.splice(0, 0, missingData.records[0]); // put it at the top of the list
                    data.records.pop(); // Remove the last item to not overflow page
                    this.documentIdToRestore = documentIdToRestore;
                } else {
                    this.notification.add(_t("Document not found or inaccessible."), {
                        type: "danger",
                    });
                }
            }
        }
    };
