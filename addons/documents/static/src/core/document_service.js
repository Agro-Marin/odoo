/** @odoo-module native */
import { AccessRightsUpdateConfirmationDialog } from "@documents/owl/components/access_update_confirmation_dialog/access_update_confirmation_dialog";
import { Document } from "./document_model.js";
import { DocumentsManageVersions } from "@documents/components/documents_manage_versions_panel/documents_manage_versions_panel";
import { openDocumentUrl } from "@documents/views/utils";
import { EventBus, markup, reactive } from "@odoo/owl";
import { browser } from "@web/core/browser/browser";
import { download, rpc } from "@web/core/network";
import { parseSearchQuery, router } from "@web/core/browser/router";
import { ConfirmationDialog } from "@web/ui/dialog";
import { serializeDate } from "@web/core/l10n/dates";
import { _t } from "@web/core/translation";
import { registry } from "@web/core/registry";
import { user } from "@web/core/user";
import { debounce } from "@web/core/utils/timing";
import { Deferred } from "@web/core/utils/concurrency";
import { session } from "@web/session";
import { formatFieldFloat } from "@web/core/formatters";

import { DateTime } from "luxon";

export class DocumentService {
    documentList;

    constructor(env, services) {
        this.env = env;
        /** @type {import("@mail/core/common/store_service").Store} */
        this.store = services["mail.store"];
        this.orm = services["orm"];
        this.action = services["action"];
        this.notification = services["notification"];
        this.dialog = services["dialog"];
        this.fileUpload = services["file_upload"];
        this.busService = services["bus_service"];
        this.logAccess = debounce(this._logAccess, 1000, false);
        this.currentFolderAccessToken = null;
        this.bus = new EventBus();
        this.userIsDocumentManager = false;
        this.userIsDocumentUser = false;
        this.userIsErpManager = false;
        this.userIsInternal = false;
        this.multiCompany = false;
        this.hasFolderEditorAccess = false;
        const urlSearch = parseSearchQuery(browser.location.search);
        const { documents_init } = session;
        const openPreview =
            Boolean(urlSearch.documents_init_open_preview) ||
            documents_init?.open_preview;
        const documentId =
            Number(urlSearch.documents_init_document_id) || documents_init?.document_id;
        this.documentIdToRestoreOnce = documentId;
        const userFolderId = urlSearch.documents_init_user_folder_id;
        this._initData = { documentId, userFolderId, openPreview };
        if (userFolderId) {
            browser.localStorage.setItem(
                "searchpanel_documents_document",
                userFolderId,
            );
        }
        this.getSelectionActions = null;
    }

    /**
     * @returns {boolean}
     */
    _readChatterVisible() {
        try {
            return Boolean(
                JSON.parse(browser.localStorage.getItem("documentsChatterVisible")),
            );
        } catch {
            return false;
        }
    }

    getOnceDocumentIdToRestore() {
        const res = this.documentIdToRestoreOnce;
        this.documentIdToRestoreOnce = undefined;
        return res;
    }

    async start() {
        [
            this.userIsDocumentManager,
            this.userIsDocumentUser,
            this.userIsErpManager,
            this.userIsInternal,
            this.multiCompany,
        ] = await Promise.all([
            user.hasGroup("documents.group_documents_manager"),
            user.hasGroup("documents.group_documents_user"),
            user.hasGroup("base.group_erp_manager"),
            user.hasGroup("base.group_user"),
            user.hasGroup("base.group_multi_company"),
        ]);
        this.hasFolderEditorAccess = this.userIsInternal;
        if (!this.hasFolderEditorAccess) {
            try {
                const destinations = await this.orm.call(
                    "documents.operation",
                    "get_any_editor_destination",
                );
                this.hasFolderEditorAccess = destinations.length > 0;
            } catch {
                // No operation wizard: nothing to move or duplicate into anyway.
            }
        }
        this.rightPanelReactive = reactive(
            {
                visible: this.userIsInternal && this._readChatterVisible(),
                focusedRecord: null,
                previewedDocument: null,
            },
            () => {
                browser.localStorage.setItem(
                    "documentsChatterVisible",
                    this.rightPanelReactive.visible,
                );
            },
        );
    }

    /**
     * @param {{id: number, attachment: Object, record: Object}} data
     * @returns {Document}
     */
    insert(data) {
        const cached = this.store.Document.records[data.id];
        if (cached?.record.id === data.record.id) {
            cached.attachment = this.store["ir.attachment"].insert(data.attachment);
            return cached;
        }
        const document = new Document();
        document.id = data.id;
        document.attachment = this.store["ir.attachment"].insert(data.attachment);
        document.record = data.record;
        this.store.Document.records[data.id] = document;
        return this.store.Document.records[data.id];
    }

    /**
     * @param {number} documentId
     * @returns {Promise<String>}
     */
    async loadEmailContent(documentId) {
        if (!this._emailContentBatch) {
            this._emailContentBatch = { ids: new Set(), deferred: new Deferred() };
            Promise.resolve().then(() => this._flushEmailContentBatch());
        }
        const batch = this._emailContentBatch;
        batch.ids.add(documentId);
        return (await batch.deferred)[documentId];
    }

    async _flushEmailContentBatch() {
        const batch = this._emailContentBatch;
        this._emailContentBatch = null;
        try {
            const records = await this.orm.read(
                "documents.document",
                [...batch.ids],
                ["raw"],
            );
            batch.deferred.resolve(
                Object.fromEntries(records.map((r) => [r.id, r.raw])),
            );
        } catch (error) {
            batch.deferred.reject(error);
        }
    }

    canUploadInFolder(folder) {
        if (!folder) {
            return false;
        }
        const userPermission = folder.target_user_permission || folder.user_permission;
        return (
            (typeof folder.id === "number" && userPermission === "edit") ||
            (this.userIsInternal && ["MY", "RECENT", false].includes(folder.id)) ||
            (this.userIsDocumentManager && folder.id === "COMPANY")
        );
    }

    canDownload(document) {
        return document && typeof document.id === "number";
    }

    async downloadDocuments(documents, resIds) {
        if (!resIds) {
            documents = documents.filter((rec) => !rec.isRequest());
            if (!documents.length) {
                return;
            }

            const linkDocuments = documents.filter((el) => el.data.type === "url");
            const noLinkDocuments = documents.filter((el) => el.data.type !== "url");
            if (documents.length === 1 && linkDocuments.length) {
                openDocumentUrl(linkDocuments[0].data.url);
                return;
            } else if (noLinkDocuments.length) {
                if (noLinkDocuments.length === 1) {
                    await download({
                        data: {},
                        url: `/documents/content/${noLinkDocuments[0].data.access_token}`,
                    });
                    return;
                } else {
                    resIds = noLinkDocuments.map((rec) => rec.data.id);
                }
            } else {
                return;
            }
        }
        await download({
            data: {
                file_ids: resIds,
                zip_name: `documents-${serializeDate(DateTime.now())}.zip`,
            },
            url: "/documents/zip",
        });
    }

    isEditable(document) {
        return (
            document &&
            typeof document.id === "number" &&
            document.user_permission === "edit" &&
            (document.user_folder_id !== "COMPANY" || this.userIsDocumentManager)
        );
    }

    isFolderSharable(folder) {
        return folder && typeof folder.id === "number";
    }

    async openDialogRename(documentId) {
        return new Promise((resolve) => {
            this.action.doAction(
                {
                    name: _t("Rename"),
                    type: "ir.actions.act_window",
                    res_model: "documents.document",
                    res_id: documentId,
                    views: [[false, "form"]],
                    target: "new",
                    context: {
                        active_id: documentId,
                        dialog_size: "medium",
                        form_view_ref: "documents.document_view_form_rename",
                    },
                },
                {
                    onClose: async () => {
                        resolve();
                    },
                },
            );
        });
    }

    async openDialogManageVersions(documentId) {
        this.dialog.add(DocumentsManageVersions, { documentId });
    }

    async openSharingDialog(documentIds) {
        const action = await this.orm.call("documents.sharing", "action_open", [
            documentIds,
        ]);
        await this.action.doAction(action, { onClose: () => this.reload() });
    }

    async openOperationDialog({
        documents,
        attachmentId,
        operation = "move",
        onClose = () => {},
        context = {},
    }) {
        documents = documents || [];
        const doc0 = documents[0];
        let name;
        const single_values = { documentName: doc0?.name };
        const multiple_values = { numberOfDocuments: documents.length.toString() };
        if (operation === "move") {
            name =
                documents.length === 1
                    ? _t("Move: %(documentName)s", single_values)
                    : _t("Move: %(numberOfDocuments)s items", multiple_values);
        } else if (operation === "shortcut") {
            name =
                documents.length === 1
                    ? _t("Create shortcut to: %(documentName)s", single_values)
                    : _t(
                          "Create shortcuts for: %(numberOfDocuments)s items",
                          multiple_values,
                      );
        } else if (operation === "copy") {
            name =
                documents.length === 1
                    ? _t("Duplicate: %(documentName)s", single_values)
                    : _t("Duplicate: %(numberOfDocuments)s items", multiple_values);
        } else if (operation === "add") {
            name = _t("Add to documents");
        } else {
            name = operation;
        }
        this.action.doAction(
            {
                name,
                type: "ir.actions.act_window",
                res_model: "documents.operation",
                views: [[false, "form"]],
                target: "new",
            },
            {
                additionalContext: {
                    default_document_ids: documents.map((d) => d.id),
                    default_attachment_id: attachmentId || false,
                    default_operation: operation,
                    ...context,
                },
                onClose,
            },
        );
    }

    /**
     * @param {String} key
     * @param {Function} factory
     * @returns {Promise<any>}
     */
    _fetchOnce(key, factory) {
        this._onceCache ??= {};
        this._onceCache[key] ??= factory();
        return this._onceCache[key];
    }

    /**
     * @returns {Promise<number>}
     */
    getDeletionDelay() {
        return this._fetchOnce("deletionDelay", () =>
            this.orm.call("documents.document", "get_deletion_delay", [[]]),
        );
    }

    /** @returns {Promise<number>} */
    getMaxUploadSize() {
        return this._fetchOnce("maxUploadSize", () =>
            this.orm.call("documents.document", "get_document_max_upload_limit"),
        );
    }

    /** @returns {Promise<String[]>} */
    getDetailsPanelResModels() {
        return this._fetchOnce("detailsPanelResModels", () =>
            this.orm.call("documents.document", "get_details_panel_res_models"),
        );
    }

    async moveToTrash(documentIds) {
        const deletionDelay = await this.getDeletionDelay();
        const confirmed = await new Promise((resolve) => {
            const dialogProps = {
                title: _t("Move to trash"),
                body: _t(
                    "Items moved to the trash will be deleted forever after %(deletion_delay)s days.",
                    { deletion_delay: deletionDelay },
                ),
                confirmLabel: _t("Move to trash"),
                cancelLabel: _t("Discard"),
                confirm: async () => resolve(true),
                cancel: () => resolve(false),
            };
            this.dialog.add(ConfirmationDialog, dialogProps);
        });
        if (!confirmed) {
            return false;
        }
        await this.orm.call("documents.document", "action_archive", [documentIds]);
        return true;
    }

    async goToServerActionsView() {
        const userHasAccessRight = await user.checkAccessRight(
            "ir.actions.server",
            "create",
        );
        if (!userHasAccessRight) {
            return this.notification.add(
                _t("Contact your Administrator to get access if needed."),
                {
                    title: _t("Access to Server Actions"),
                    type: "info",
                },
            );
        }

        return await this.action.doActionButton({
            name: "action_open_documents_server_action_view",
            type: "object",
            resModel: "ir.actions.server",
        });
    }

    async moveOrCreateShortcut(
        records,
        targetFolder,
        forceShortcut,
        expectedAccessRightsChanges,
    ) {
        let message = "";
        const userFolderId = targetFolder.id.toString();
        if (forceShortcut) {
            await this.orm.call("documents.document", "action_create_shortcut", [
                records.all,
                userFolderId,
            ]);
            message =
                records.all.length === 1
                    ? _t("A shortcut has been created.")
                    : _t("%s shortcuts have been created.", records.all.length);
        } else {
            if (records.movableRecordIds.length) {
                message =
                    records.movableRecordIds.length === 1
                        ? _t("The document has been moved.")
                        : _t(
                              "%s documents have been moved.",
                              records.movableRecordIds.length,
                          );
                if (expectedAccessRightsChanges) {
                    const confirmed = await new Promise((resolve) => {
                        this.dialog.add(AccessRightsUpdateConfirmationDialog, {
                            destinationFolder: targetFolder,
                            confirm: async () => resolve(true),
                            cancel: () => resolve(false),
                        });
                    });
                    if (!confirmed) {
                        return;
                    }
                }
                await this.orm.write("documents.document", records.movableRecordIds, {
                    user_folder_id: userFolderId,
                });
            }
            if (records.nonMovableRecordIds.length) {
                this.notification.add(
                    _t(
                        "At least one document could not be moved due to access rights.",
                    ),
                    { type: "warning" },
                );
            }
        }
        if (message) {
            this.notification.add(message, { type: "success" });
        }
    }

    async moveToCompanyRoot(records) {
        if (!records.movableRecordIds.length) {
            return this.notification.add(
                _t("You can't move this/those folder(s) to the Company root."),
                { type: "warning" },
            );
        }
        await this.orm.write("documents.document", records.movableRecordIds, {
            user_folder_id: "COMPANY",
        });
        let message =
            records.movableRecordIds.length === 1
                ? _t("The document/folder has been moved to the Company root.")
                : _t(
                      "%s documents/folders have been moved to the Company root.",
                      records.movableRecordIds.length,
                  );
        if (records.nonMovableRecordIds.length) {
            message = markup`${message}<br/>${_t("At least one document hasn't been moved.")}`;
        }
        this.notification.add(message, {
            type: records.nonMovableRecordIds.length ? "warning" : "success",
        });
    }

    async toggleFavorite(document) {
        await this.orm.write("documents.document", [document.id], {
            is_favorited: !document.is_favorited,
        });
    }

    get initData() {
        return this._initData;
    }

    reload() {
        this.bus.trigger("DOCUMENT_RELOAD");
    }

    /**
     * @param {object} folderChange
     * @param {object[]} inspectedDocuments
     * @param {boolean} forceInspected
     */
    updateDocumentURL(folderChange, inspectedDocuments, forceInspected) {
        let accessToken = undefined;
        if (folderChange) {
            accessToken = folderChange.access_token;
            this.currentFolderAccessToken = accessToken;
        } else if (inspectedDocuments && inspectedDocuments.length === 1) {
            const record = inspectedDocuments[0];
            if (
                forceInspected ||
                record.selected ||
                record.isContainer ||
                this.rightPanelReactive.previewedDocument?.record.id === record.id
            ) {
                accessToken = record.data.access_token;
            }
        } else if (!inspectedDocuments || inspectedDocuments.length === 0) {
            accessToken = this.currentFolderAccessToken;
        }
        router.pushState({ access_token: accessToken || undefined });
    }

    updateDocumentURLRefresh() {
        const tokenToShow =
            this.focusedRecord?.data.access_token || this.currentFolderAccessToken;
        if (tokenToShow) {
            router.pushState({ access_token: tokenToShow });
        }
    }

    /**
     * @param {String} accessToken
     * @returns {Promise<Object|undefined>}
     */
    async _logAccess(accessToken) {
        if (!accessToken) {
            return;
        }
        try {
            return await rpc(`/documents/touch/${encodeURIComponent(accessToken)}`);
        } catch {
            return undefined;
        }
    }

    async getActions(folderId) {
        if (!this.userIsInternal) {
            return [];
        }
        return await this.orm.call("documents.document", "get_documents_actions", [
            folderId,
        ]);
    }

    async enableAction(folderId, actionId) {
        return await this.orm.call("documents.document", "action_folder_embed_action", [
            folderId,
            actionId,
        ]);
    }

    get focusedRecord() {
        return this.rightPanelReactive.focusedRecord;
    }

    focusRecord(record, forceSelected) {
        if (this.focusedRecord !== record) {
            this.rightPanelReactive.focusedRecord = record;
            this.updateDocumentURL(null, record ? [record] : null, forceSelected);
            if (record) {
                this.logAccess(record.data.access_token);
            }
        }
    }

    stopRightPanelScrollObserver() {
        this.observer?.disconnect();
        this.observer = undefined;
    }

    toggleRightPanelVisibility() {
        this.rightPanelReactive.visible = !this.rightPanelReactive.visible;

        this.stopRightPanelScrollObserver();

        if (this.rightPanelReactive.visible) {
            this.observer = new MutationObserver(() => {
                const chatterContainer = document.querySelector(".o-mail-Thread");
                if (chatterContainer && this.env.isSmall) {
                    chatterContainer.scrollIntoView({ behavior: "smooth" });
                    this.observer.disconnect();
                    return;
                }
                const view = this.action.currentController?.props.type;
                if (chatterContainer && ["kanban", "list"].includes(view)) {
                    const selectedRecordClass =
                        view === "kanban"
                            ? ".o_kanban_record.o_record_selected"
                            : ".o_data_row.o_data_row_selected";
                    const selectedRecords =
                        document.querySelectorAll(selectedRecordClass);
                    if (selectedRecords?.length > 0) {
                        selectedRecords[0].scrollIntoView({
                            behavior: "instant",
                            block: view === "kanban" ? "start" : "center",
                        });
                    }
                    this.observer.disconnect();
                }
            });
            const content = document.querySelector(".o_documents_content");
            if (content) {
                this.observer.observe(content, { childList: true, subtree: true });
            }
        }
    }

    setPreviewedDocument(document) {
        this.rightPanelReactive.previewedDocument = document;
        if (document) {
            this.focusRecord(document.record);
        }
    }

    /**
     * @param {FileList|File[]} files
     * @param {String} accessToken
     * @param {Object} [context]
     * @param {Object} [param3]
     * @param {number|String} [param3.targetFolderId]
     */
    async uploadDocument(files, accessToken, context, { targetFolderId } = {}) {
        const fileArray = [...files];
        const maxUploadSize = await this.getMaxUploadSize();
        const validFiles = fileArray.filter((file) => file.size <= maxUploadSize);
        if (validFiles.length !== 0) {
            const encodedToken = encodeURIComponent(accessToken || "");
            const uploadRoute = `/documents/upload/${encodedToken}`;
            const upload = await this.fileUpload.upload(uploadRoute, validFiles, {
                buildFormData: (formData) => {
                    if (context) {
                        for (const key of [
                            "default_user_folder_id",
                            "default_partner_id",
                            "default_res_id",
                            "default_res_model",
                        ]) {
                            if (context[key]) {
                                formData.append(
                                    key.replace("default_", ""),
                                    context[key],
                                );
                            }
                        }
                        if (context.allowed_company_ids) {
                            formData.append(
                                "allowed_company_ids",
                                JSON.stringify(context.allowed_company_ids),
                            );
                        }
                    }
                },
                displayErrorNotification: false,
            });
            const trackedUpload = upload && this.fileUpload.uploads[upload.id];
            if (trackedUpload && targetFolderId !== undefined) {
                trackedUpload.targetFolderId = targetFolderId;
            }
        }
        if (validFiles.length >= fileArray.length) {
            return;
        }
        const message = _t(
            "Some files could not be uploaded (max size: %s).",
            formatFieldFloat(maxUploadSize, { humanReadable: true }),
        );
        this.notification.add(message, { type: "danger" });
    }
}

export const documentService = {
    dependencies: [
        "action",
        "bus_service",
        "dialog",
        "file_upload",
        "mail.store",
        "notification",
        "orm",
    ],
    async start(env, services) {
        const service = new DocumentService(env, services);
        await service.start();
        return service;
    },
};

registry.category("services").add("document.document", documentService);
