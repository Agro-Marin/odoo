/** @odoo-module native */
import { _t } from "@web/core/translation";
import { openDocumentUrl, toFolderValueId } from "@documents/views/utils";

/** Mimetypes the file viewer can render. */
const VIEWABLE_MIMETYPES = new Set([
    "image/bmp",
    "image/gif",
    "image/jpeg",
    "image/png",
    "image/svg+xml",
    "image/tiff",
    "image/x-icon",
    "image/webp",
    "application/documents-email",
    "application/javascript",
    "application/json",
    "application/xml",
    "text/xml",
    "text/x-python",
    "text/markdown",
    "text/css",
    "text/calendar",
    "text/javascript",
    "text/html",
    "text/plain",
    "application/pdf",
    "application/pdf;base64",
    "audio/mpeg",
    "video/x-matroska",
    "video/mp4",
    "video/webm",
]);

/**
 * Deliberately as loose as `FileModel.isYoutubeVideo`
 * (`web/static/src/components/file_viewer/file_model.js`), which is what decides
 * whether the viewer renders an embed: a stricter test here would call URLs the
 * viewer can show non-viewable.
 *
 * @param {String|false} url
 * @returns {boolean}
 */
function isYoutubeUrl(url) {
    return typeof url === "string" && url.includes("youtu");
}

export const DocumentsRecordMixin = (component) =>
    class extends component {
        setup(config, data) {
            super.setup(...arguments);
            // Set by `_loadDocumentToRestore` on the model driving this load.
            if (data.id === this.model.documentIdToRestore) {
                this.selected = true;
            }
        }

        async update(changes, options = {}) {
            if ("name" in changes && !changes.name) {
                this.model.env.services.notification.add(_t("Name cannot be empty."), {
                    type: "danger",
                });
                if (Object.keys(changes).length === 1) {
                    this._discard();
                    return;
                }
                delete changes.name;
                this._setEvalContext();
            }
            const modelMultiEdit = this.model.multiEdit;
            // Only move the whole selection when this record is actually part of a
            // multi-edit; editing an unselected row (e.g. inline) must move that
            // row alone, not the current selection.
            let movedRecordsIds =
                this.selected && this.model.multiEdit
                    ? this.model.root.selection.map((rec) => rec.id)
                    : [this.id];
            if (this.isDetailsPanelRecord) {
                // As previewed/focused documents are not necessarily selected,
                // force `save=true` to save any changes as the record is updated
                options.save = true;
                // Prevent multiEditing/moving the (whole) selection as it is not what we intend to modify when previewing.
                this.model.multiEdit = false;
                movedRecordsIds = [this.id];
            }
            // A document at the root has `folder_id === false`, not a m2o object,
            // so normalize both sides: `false.id` is `undefined`, which would make
            // a move to or from the root look like "no change".
            const originalFolderId = this.data.folder_id?.id ?? false;
            let ret;
            try {
                ret = await super.update(changes, options);
            } finally {
                // Restore multiEdit even if the save rejects, otherwise a single
                // failed details-panel edit disables multi-edit for the session.
                this.model.multiEdit = modelMultiEdit;
            }
            if ((this.data.folder_id?.id ?? false) !== originalFolderId) {
                this.model.root._removeRecords(movedRecordsIds);
                // Same as moving when not in preview
                this.model.env.documentsView.bus.trigger("documents-close-preview");
            }
            if (this.isDetailsPanelRecord && this.data.type === "folder") {
                this.model.env.searchModel._reloadSearchPanel();
            }
            return ret;
        }

        isPdf() {
            return (
                this.data.mimetype === "application/pdf" ||
                this.data.mimetype === "application/pdf;base64"
            );
        }

        isRequest() {
            return (
                !this.data.shortcut_document_id &&
                this.data.type === "binary" &&
                !this.data.attachment_id
            );
        }

        isShortcut() {
            return !!this.data.shortcut_document_id;
        }

        isURL() {
            return !this.data.shortcut_document_id && this.data.type === "url";
        }

        /**
         * Return the source Document if this is a shortcut and self if not.
         */
        get shortcutTarget() {
            if (!this.isShortcut()) {
                return this;
            }
            return (
                this.model.shortcutTargetRecords.find(
                    (rec) => rec.resId === this.data.shortcut_document_id.id
                ) || this
            );
        }

        hasStoredThumbnail() {
            return this.data.thumbnail_status === "present";
        }

        isViewable() {
            const { type, mimetype, url } = this.shortcutTarget.data;
            return (
                type !== "folder" &&
                (VIEWABLE_MIMETYPES.has(mimetype) || isYoutubeUrl(url))
            );
        }

        async onClickPreview(ev) {
            if (this.isRequest()) {
                ev.stopPropagation();
                // kanban view support
                ev.target.querySelector(".o_kanban_replace_document")?.click();
            } else if (this.isViewable()) {
                ev.stopPropagation();
                ev.preventDefault();
                const selection = this.model.root.selection;
                const documents = (selection.length > 1 &&
                    selection.find((rec) => rec === this) &&
                    selection.filter((rec) => rec.isViewable())) || [this];

                // Load the embeddedActions in case we open the split tool
                const embeddedActions =
                    this.data.available_embedded_actions_ids?.records.map((rec) => ({
                        id: rec.resId,
                        name: rec.data.display_name,
                    })) || [];

                await this.model.env.documentsView.bus.trigger("documents-open-preview", {
                    documents,
                    mainDocument: this,
                    isPdfSplit: false,
                    embeddedActions,
                });
            } else if (this.isURL()) {
                openDocumentUrl(this.data.url);
            }
        }

        async openFolder() {
            const target = this.isShortcut() ? this.shortcutTarget : this;
            const folderId = target.data.active ? target.data.id : "TRASH";
            await this._goToFolder(folderId);
        }

        /**
         * Jump to shortcut targeted file / open targeted folder.
         */
        async jumpToTarget() {
            const target = this.shortcutTarget;
            let folderId;
            if (!target.data.active) {
                folderId = "TRASH";
            } else if (target.data.type === "folder") {
                // Using doc data shortcut_document_id because isContainer record does not (need to) load shortcutTarget.
                folderId = this.data.shortcut_document_id?.id || target.data.id;
            } else {
                folderId = toFolderValueId(target.data.user_folder_id);
            }
            if (!folderId) {
                // `_compute_user_folder_id` answers `false` for a document the
                // user cannot access, so a shortcut can point at a target whose
                // location is not disclosed. Say so instead of navigating to a
                // folder id that matches nothing.
                this.model.notification.add(_t("Document not found or inaccessible."), {
                    type: "danger",
                });
                return;
            }
            await this._goToFolder(folderId);
        }

        /**
         * Select `folderId` in the search panel and unfold its chain, reloading
         * the panel first when it does not hold that folder yet.
         *
         * @param {number|String} folderId
         */
        async _goToFolder(folderId) {
            const searchModel = this.model.env.searchModel;
            if (!searchModel.getFolderById(folderId)) {
                await searchModel._reloadSearchModel(true);
            }
            searchModel.toggleCategoryValue(searchModel.folderCategory.id, folderId);
            this.model.originalSelection = [this.shortcutTarget.resId];
            this.model.env.documentsView.bus.trigger("documents-expand-folder", { folderId });
        }
    };
