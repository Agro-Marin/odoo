/** @odoo-module native */
import { registry } from "@web/core/registry";
import { _t } from "@web/core/translation";
import { user } from "@web/core/user";
import { useBus, useService } from "@web/core/utils/hooks";
import { htmlJoin } from "@web/core/utils/dom/html";
import { useSetupAction } from "@web/core/action_hook";
import { PdfManager } from "@documents/owl/components/pdf_manager/pdf_manager";
import {
    EventBus,
    onMounted,
    onWillStart,
    markup,
    useComponent,
    useEnv,
    useRef,
    useSubEnv,
} from "@odoo/owl";

export const DETAIL_PANEL_REQUIRED_FIELDS = [
    "lock_uid",
    "shortcut_document_id",
    "res_name",
    "res_model_name",
    "file_size",
    "res_model",
    "mail_alias_domain_count",
    "alias_name",
    "alias_domain_id",
    "alias_email",
    "create_activity_type_id",
    "type",
    "name",
    "folder_id",
    "company_id",
    "owner_id",
    "user_permission",
    "partner_id",
    "tag_ids",
];

export function preSuperSetupFolder() {
    const component = useComponent();
    const documentService = useService("document.document");
    onWillStart(async () => {
        component._deletionDelay = await documentService.getDeletionDelay();
    });
}

export function preSuperSetup() {
    useSubEnv({
        documentsView: {
            bus: new EventBus(),
        },
    });
    const component = useComponent();
    const props = component.props;
    if (props.globalState && props.globalState.sharedSelection) {
        if (!props.state) {
            props.state = {};
        }
        if (!props.state.modelState) {
            props.state.modelState = {};
        }
        props.state.modelState.sharedSelection = props.globalState.sharedSelection;
    }
}

export function useDocumentView(helpers) {
    const component = useComponent();
    const props = component.props;
    const root = useRef("root");
    const orm = useService("orm");
    const notification = useService("notification");
    const dialogService = useService("dialog");
    const action = useService("action");
    const documentService = useService("document.document");

    useSubEnv({
        model: component.model,
    });
    const env = useEnv();
    const bus = env.documentsView.bus;

    const _openAutomations = async ({ folderId, folderDisplayName }) => {
        const checkBaseAutomation = await orm.call(
            "documents.document",
            "check_automation_available"
        );
        if (!checkBaseAutomation) {
            const UpsellDialog = registry
                .category("documents_automation_upsell")
                .get("dialog", null);
            if (UpsellDialog) {
                return dialogService.add(UpsellDialog, {
                    title: _t("Odoo Studio - Customize workflows in minutes"),
                });
            }
            return notification.add(
                _t("Install an automation app to build rules on this folder."),
                { title: _t("Access to Automations"), type: "info" }
            );
        }
        const userHasAccessRight = await user.checkAccessRight("base.automation", "create");
        if (!userHasAccessRight) {
            return notification.add(_t("Contact your Administrator to get access if needed."), {
                title: _t("Access to Automations"),
                type: "info",
            });
        }
        const documentsModelId = await orm.search(
            "ir.model",
            [["model", "=", "documents.document"]],
            { limit: 1 }
        );
        return await action.doAction("base_automation.base_automation_act", {
            additionalContext: {
                active_test: false,
                default_model_id: documentsModelId[0],
                search_default_model_id: documentsModelId[0],
                default_name: _t("Put in %s", folderDisplayName),
                default_filter_domain: [["folder_id", "in", [folderId]]],
                default_trigger: "on_create_or_write",
            },
        });
    };

    /**
     * @returns {number|false}
     */
    const selectedRealFolderId = () => {
        const folderId = env.searchModel.getSelectedFolderId();
        return typeof folderId === "number" ? folderId : false;
    };

    useSetupAction({
        rootRef: root,
        getGlobalState: () => ({
            sharedSelection: component.model.exportSelection(),
        }),
    });

    useBus(bus, "documents-open-automations", (ev) => {
        _openAutomations(ev.detail);
    });

    onMounted(async () => {
        documentService.updateDocumentURLRefresh();
    });

    return {
        root,
        orm,
        notification,
        dialogService,
        actionService: action,
        ...useDocumentsViewFilePreviewer(helpers),
        canUploadInFolder: (folder) => documentService.canUploadInFolder(folder),
        ...useDocumentsViewFileUpload(),
        ...useEmbeddedAction(),
        hasShareDocuments: () => {
            const folder = env.searchModel.getSelectedFolder();
            const selectedRecords = env.model.root.selection.length;
            return typeof folder.id !== "number" && !selectedRecords;
        },
        userIsInternal: documentService.userIsInternal,
        userIsDocumentManager: documentService.userIsDocumentManager,
        onClickDocumentsRequest: () => {
            action.doAction("documents.action_request_form", {
                additionalContext: {
                    default_partner_id: props.context.default_partner_id || false,
                    default_folder_id: selectedRealFolderId(),
                    default_res_id: props.context.default_res_id || false,
                    default_res_model: props.context.default_res_model || false,
                    default_requestee_id: props.context.default_partner_id || false,
                },
                fullscreen: env.isSmall,
                onClose: async () => {
                    await env.model.load();
                    env.model.notify();
                },
            });
        },
        onClickDocumentsAddUrl: () => {
            const folderId = env.searchModel.getSelectedFolderId();
            action.doAction("documents.action_url_form", {
                additionalContext: {
                    default_type: "url",
                    default_partner_id: props.context.default_partner_id || false,
                    default_folder_id: selectedRealFolderId(),
                    default_res_id: props.context.default_res_id || false,
                    default_res_model: props.context.default_res_model || false,
                    ...(folderId === "COMPANY" ? { default_owner_id: false } : {}),
                },
                fullscreen: env.isSmall,
                onClose: async () => {
                    await env.model.load();
                    env.model.notify();
                },
            });
        },
        onClickAddFolder: () => {
            const currentFolder = env.searchModel.getSelectedFolderId();
            action.doAction("documents.action_folder_form", {
                additionalContext: {
                    default_type: "folder",
                    default_user_folder_id: currentFolder ? currentFolder.toString() : "MY",
                    ...(currentFolder === "COMPANY" ? { default_access_internal: "edit" } : {}),
                },
                fullscreen: env.isSmall,
                onClose: async () => {
                    await env.searchModel._reloadSearchModel(true);
                    bus.trigger("documents-expand-folder", {
                        folderId: [false, "COMPANY"].includes(currentFolder) ? "MY" : currentFolder,
                    });
                },
            });
        },
        onClickShareFolder: async () => {
            if (env.model.root.selection.length > 0) {
                if (env.model.root.selection.length !== 1) {
                    return;
                }
                const rec = env.model.root.selection[0];
                await documentService.openSharingDialog([rec.resId]);
            } else {
                const folder = env.searchModel.getSelectedFolder();
                await documentService.openSharingDialog([folder.id]);
            }
        },
    };
}

function useDocumentsViewFilePreviewer({
    getSelectedDocumentsElements,
    setPreviewStore,
    isRecordPreviewable = () => true,
}) {
    const component = useComponent();
    const env = useEnv();
    const bus = env.documentsView.bus;
    /** @type {import("@documents/core/document_service").DocumentService} */
    const documentService = useService("document.document");
    /** @type {import("@mail/core/common/store_service").Store} */
    const store = useService("mail.store");

    const onOpenDocumentsPreview = async ({
        documents,
        mainDocument,
        isPdfSplit,
        embeddedActions,
    }) => {
        const openPdfSplitter = (documents) => {
            let newDocumentIds = [];
            let forceDelete = false;
            component.dialogService.add(
                PdfManager,
                {
                    documents: documents.map((doc) => doc.data),
                    embeddedActions,
                    onProcessDocuments: async ({
                        documentIds,
                        actionId,
                        exit,
                        isForcingDelete,
                    }) => {
                        forceDelete = isForcingDelete;
                        if (documentIds && documentIds.length) {
                            newDocumentIds = [...new Set(newDocumentIds.concat(documentIds))];
                        }
                        if (actionId) {
                            await component.embeddedAction(documentIds, actionId, !exit);
                        }
                    },
                },
                {
                    onClose: async () => {
                        if (!newDocumentIds.length && !forceDelete) {
                            return;
                        }
                        await component.model.load();
                        for (const record of documents) {
                            if (!newDocumentIds.includes(record.resId)) {
                                await record.model.root.deleteRecords([record]);
                            }
                        }
                        for (const record of env.model.root.records.filter((r) =>
                            newDocumentIds.includes(r.resId)
                        )) {
                            record.toggleSelection(true);
                        }
                    },
                }
            );
        };
        if (isPdfSplit) {
            setPreviewStore({});
            openPdfSplitter(documents);
            return;
        }
        const documentsRecords = (
            (documents.length === 1 && component.model.root.records) ||
            documents
        )
            .filter((rec) => isRecordPreviewable(rec) && rec.isViewable())
            .map((rec) => {
                const getRecordAttachment = (rec) => {
                    rec = rec.shortcutTarget;
                    return {
                        id: -rec.resId,
                        name: rec.data.name,
                        mimetype: rec.data.mimetype,
                        url: rec.data.url,
                        documentId: rec.resId,
                        documentData: rec.data,
                    };
                };
                return store.Document.insert({
                    id: rec.resId,
                    attachment: getRecordAttachment(rec),
                    record: rec,
                });
            });
        const documentsViewEl = () =>
            component.root?.el?.querySelector(".o_documents_view");
        documentsViewEl()?.classList.add("overflow-hidden");
        const selectedDocument = documentsRecords.find(
            (rec) => rec.id === (mainDocument || documents[0]).resId
        );
        documentService.documentList = {
            documents: documentsRecords || [],
            folderId: env.searchModel.getSelectedFolderId(),
            initialRecordSelectionLength: documents.length,
            onDeleteCallback: () => {
                const elements = getSelectedDocumentsElements();
                if (elements.length) {
                    elements[0].focus();
                    const focusedDocument = documentService.documentList.documents.find(
                        (d) => d.record.id === elements[0].dataset.id
                    );
                    documentService.focusRecord(focusedDocument?.record || null);
                }
                documentsViewEl()?.classList.remove("overflow-hidden");

                setPreviewStore({});
                documentService.documentList = null;
            },
            selectedDocument,
        };

        const previewStore = {
            documentList: documentService.documentList,
            startIndex: documentsRecords.indexOf(selectedDocument),
            attachments: documentsRecords.map((doc) => doc.attachment),
        };

        documentService.setPreviewedDocument(selectedDocument);

        setPreviewStore({ ...previewStore });
    };

    useBus(bus, "documents-open-preview", async (ev) => {
        component.onOpenDocumentsPreview(ev.detail);
    });
    useBus(bus, "documents-close-preview", () => {
        documentService.setPreviewedDocument(null);
        documentService.documentList?.onDeleteCallback();
    });

    return {
        onOpenDocumentsPreview,
    };
}

function useDocumentsViewFileUpload() {
    const component = useComponent();
    const env = useEnv();
    const bus = env.documentsView.bus;
    const notification = useService("notification");
    const fileUpload = useService("file_upload");
    const documentService = useService("document.document");

    const handleUploadError = (result) => {
        notification.add(result.error, {
            type: "danger",
            sticky: true,
        });
    };

    useBus(fileUpload.bus, "FILE_UPLOAD_ERROR", async (ev) => {
        const { upload } = ev.detail;
        if (upload.state !== "error") {
            return;
        }
        handleUploadError({
            error: _t("An error occured while uploading."),
        });
    });

    useBus(documentService.bus, "DOCUMENT_RELOAD", async () => {
        await env.searchModel._reloadSearchModel(true);
        await env.model.load();
        await env.model.notify();
    });

    useBus(fileUpload.bus, "FILE_UPLOAD_LOADED", async (ev) => {
        const { upload } = ev.detail;
        const xhr = upload.xhr;
        if (xhr.status !== 200) {
            handleUploadError({
                error: _t("status code: %(status)s, message: %(message)s", {
                    status: xhr.status,
                    message: xhr.response,
                }),
            });
            return;
        }
        let response;
        try {
            response = JSON.parse(xhr.response);
        } catch {
            handleUploadError({
                error: _t("The server returned an unexpected response to the upload."),
            });
            return;
        }
        const newDocumentIds = Array.isArray(response) ? response : undefined;
        await env.model.load();
        if (!newDocumentIds) {
            return;
        }
        component.model.root.selection.forEach((el) => el.toggleSelection(false));
        const newRecords = env.model.root.records.filter((r) => newDocumentIds.includes(r.resId));
        newRecords.map((record) => record.toggleSelection(true));
        documentService.focusRecord(newRecords[0]);
    });

    const uploadFiles = async ({ files, accessToken, context }) => {
        const selectedUserFolderId = env.searchModel.getSelectedFolderId() || "MY";
        const uploadContext = ["COMPANY", "MY"].includes(selectedUserFolderId)
            ? { ...context, default_user_folder_id: selectedUserFolderId }
            : context;
        await documentService.uploadDocument(files, accessToken, uploadContext, {
            targetFolderId: selectedUserFolderId,
        });
    };

    useBus(bus, "documents-upload-files", (ev) => {
        component.uploadFiles({
            ...ev.detail,
            context: {
                ...component.props.context,
                ...ev.detail.context,
            },
        });
    });

    return {
        uploadFiles,
        onFileInputChange: async (ev) => {
            if (!ev.target.files.length) {
                return;
            }
            await component.uploadFiles({
                files: ev.target.files,
                accessToken: documentService.currentFolderAccessToken,
                context: component.props.context,
            });
            ev.target.value = "";
        },
    };
}

export function useEmbeddedAction() {
    const env = useEnv();
    const orm = useService("orm");
    const notification = useService("notification");
    const action = useService("action");
    return {
        embeddedAction: async (documentIds, actionId, preventReload = false) => {
            const context = {
                active_model: "documents.document",
                active_ids: documentIds,
            };
            const result = await orm.call(
                "documents.document",
                "action_execute_embedded_action",
                [actionId],
                {
                    context,
                }
            );

            if (result && typeof result === "object") {
                if (Object.prototype.hasOwnProperty.call(result, "warning")) {
                    notification.add(
                        markup`<ul>${htmlJoin(
                            result["warning"]["documents"].map((d) => markup`<li>${d}</li>`)
                        )}</ul>`,
                        {
                            title: result["warning"]["title"],
                            type: "danger",
                        }
                    );
                    if (!preventReload) {
                        await env.model.load();
                    }
                } else if (!preventReload) {
                    await action.doAction(result, {
                        onClose: async () => await env.model.load(),
                    });
                    return;
                }
            } else if (!preventReload) {
                await env.model.load();
            }
        },
    };
}
