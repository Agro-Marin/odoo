/** @odoo-module native */
import { EventBus } from "@odoo/owl";
import { registry } from "@web/core/registry";
import { _t } from "@web/core/translation";
import { Deferred } from "@web/core/utils/concurrency";
export class AttachmentUploadService {
    /**
     * @param {import("@web/env").OdooEnv} env
     * @param {{ file_upload: any, "mail.store": any, notification: any }} services
     */
    constructor(env, services) {
        this.setup(env, services);
    }

    /**
     * @param {import("@web/env").OdooEnv} env
     * @param {{ file_upload: any, "mail.store": any, notification: any }} services
     */
    setup(env, services) {
        this.env = env;
        this.fileUploadService = services["file_upload"];
        /** @type {import("@mail/core/common/store_service").Store} */
        this.store = services["mail.store"];
        this.notificationService = services["notification"];

        this.nextId = -1;
        this.abortByAttachmentId = new Map();
        this.deferredByAttachmentId = new Map();
        this.tmpUrlByAttachmentId = new Map();
        this.uploadingAttachmentIds = new Set();
        this._fileUploadBus = new EventBus();
        /** @type {Map<number, {composer: import("models").Composer, thread: import("models").Thread}>} */
        this.targetsByTmpId = new Map();
        this.fileUploadService.bus.addEventListener(
            "FILE_UPLOAD_ADDED",
            /** @param {CustomEvent<{upload: {data: FormData, xhr: XMLHttpRequest, type: string, title: string, res_model: string}}>} ev */
            ({ detail: { upload } }) => {
                const tmpId = parseInt(upload.data.get("temporary_id"));
                if (!this.uploadingAttachmentIds.has(tmpId)) {
                    return;
                }
                const { thread, composer } = this.targetsByTmpId.get(tmpId);
                const tmpUrl = upload.data.get("tmp_url");
                this.abortByAttachmentId.set(tmpId, upload.xhr.abort.bind(upload.xhr));
                const attachment = this.store["ir.attachment"].insert(
                    this._makeAttachmentData(
                        upload,
                        tmpId,
                        composer ? undefined : thread,
                        tmpUrl,
                    ),
                );
                composer?.attachments.push(attachment);
            },
        );
        this.fileUploadService.bus.addEventListener(
            "FILE_UPLOAD_LOADED",
            /** @param {CustomEvent<{upload: {data: FormData, xhr: XMLHttpRequest, type: string, title: string, res_model: string}}>} ev */
            ({ detail: { upload } }) => {
                const tmpId = parseInt(upload.data.get("temporary_id"));
                if (!this.uploadingAttachmentIds.has(tmpId)) {
                    return;
                }
                const def = this.deferredByAttachmentId.get(tmpId);
                if (upload.xhr.status === 413) {
                    this.notificationService.add(_t("File too large"), {
                        type: "danger",
                    });
                    def.resolve();
                    this._cleanupUploading(tmpId);
                    return;
                }
                if (upload.xhr.status !== 200) {
                    this.notificationService.add(_t("Server error"), {
                        type: "danger",
                    });
                    def.resolve();
                    this._cleanupUploading(tmpId);
                    return;
                }
                let response;
                try {
                    response = JSON.parse(upload.xhr.response);
                } catch {
                    this.notificationService.add(_t("Server error"), {
                        type: "danger",
                    });
                    def.resolve();
                    this._cleanupUploading(tmpId);
                    return;
                }
                if (response.error) {
                    this.notificationService.add(response.error, { type: "danger" });
                    def.resolve();
                    this._cleanupUploading(tmpId);
                    return;
                }
                const { thread, composer } = this.targetsByTmpId.get(tmpId);
                this._processLoaded(thread, composer, response, tmpId, def);
            },
        );
        this.fileUploadService.bus.addEventListener(
            "FILE_UPLOAD_ERROR",
            /** @param {CustomEvent<{upload: {data: FormData, xhr: XMLHttpRequest, type: string, title: string, res_model: string}}>} ev */
            ({ detail: { upload } }) => {
                const tmpId = parseInt(upload.data.get("temporary_id"));
                if (!this.uploadingAttachmentIds.has(tmpId)) {
                    return;
                }
                this.deferredByAttachmentId.get(tmpId).resolve();
                this._cleanupUploading(tmpId);
            },
        );
    }

    /**
     * @param {import("models").Thread} thread
     * @param {import("models").Composer|undefined} composer
     * @param {{data: {store_data: Object, attachment_id: number}}} response
     * @param {number} tmpId
     * @param {import("@web/core/utils/concurrency").Deferred} def
     */
    _processLoaded(thread, composer, { data }, tmpId, def) {
        const { store_data, attachment_id } = data;
        this.store.insert(store_data);
        /** @type {import("models").Attachment} */
        const attachment = this.store["ir.attachment"].get(attachment_id);
        if (composer) {
            const index = composer.attachments.findIndex(({ id }) => id === tmpId);
            if (index >= 0) {
                composer.attachments[index] = attachment;
            } else {
                composer.attachments.push(attachment);
            }
        }
        def.resolve(attachment);
        this._fileUploadBus.trigger("UPLOAD", thread);
        this._cleanupUploading(tmpId);
    }

    /** @param {number} tmpId */
    _cleanupUploading(tmpId) {
        this.abortByAttachmentId.delete(tmpId);
        this.deferredByAttachmentId.delete(tmpId);
        this.uploadingAttachmentIds.delete(tmpId);
        this.targetsByTmpId.delete(tmpId);
        const tmpUrl = this.tmpUrlByAttachmentId.get(tmpId);
        if (tmpUrl) {
            URL.revokeObjectURL(tmpUrl);
            this.tmpUrlByAttachmentId.delete(tmpId);
        }
        this.store["ir.attachment"].get(tmpId)?.remove();
    }

    /**
     * @param {import("models").Thread} thread
     * @returns {string}
     */
    getUploadURL(thread) {
        return "/mail/attachment/upload";
    }

    /** @param {import("models").Attachment} attachment */
    async unlink(attachment) {
        if (this.uploadingAttachmentIds.has(attachment.id)) {
            const deferred = this.deferredByAttachmentId.get(attachment.id);
            const abort = this.abortByAttachmentId.get(attachment.id);
            this._cleanupUploading(attachment.id);
            deferred?.resolve();
            abort?.();
            return;
        }
        await attachment.remove();
    }

    /**
     * @param {import("models").Thread} thread
     * @param {import("models").Composer|undefined} composer
     * @param {File} file
     * @param {Object} [options]
     * @param {import("models").Activity} [options.activity]
     * @returns {Promise<import("models").Attachment|undefined>}
     */
    async upload(thread, composer, file, options) {
        const tmpId = this.nextId--;
        const tmpURL = URL.createObjectURL(file);
        return this._upload(thread, composer, file, options, tmpId, tmpURL);
    }

    /**
     * @param {import("models").Thread} thread
     * @param {import("models").Composer|undefined} composer
     * @param {File} file
     * @param {Object} [options]
     * @param {number} tmpId
     * @param {string} tmpURL
     * @returns {Promise<import("models").Attachment|undefined>}
     */
    async _upload(thread, composer, file, options, tmpId, tmpURL) {
        this.targetsByTmpId.set(tmpId, { composer, thread });
        this.tmpUrlByAttachmentId.set(tmpId, tmpURL);
        this.uploadingAttachmentIds.add(tmpId);
        const uploadDoneDeferred = new Deferred();
        this.deferredByAttachmentId.set(tmpId, uploadDoneDeferred);
        await this.fileUploadService
            .upload(this.getUploadURL(thread), [file], {
                /** @param {FormData} formData */
                buildFormData: (formData) => {
                    this._buildFormData(
                        formData,
                        tmpURL,
                        thread,
                        composer,
                        tmpId,
                        options,
                    );
                },
            })
            .catch((e) => {
                if (e.name !== "AbortError") {
                    throw e;
                }
            });
        return uploadDoneDeferred;
    }

    /**
     * @param {import("models").Thread} thread
     * @param {() => void} onFileUploaded
     */
    onFileUploaded(thread, onFileUploaded) {
        this._fileUploadBus.addEventListener(
            "UPLOAD",
            /** @param {CustomEvent<import("models").Thread>} ev */ ({ detail }) => {
                if (thread.eq(detail)) {
                    onFileUploaded();
                }
            },
        );
    }

    /**
     * @param {FormData} formData
     * @param {string} tmpURL
     * @param {import("models").Thread} thread
     * @param {import("models").Composer|undefined} composer
     * @param {number} tmpId
     * @param {Object} [options]
     * @param {import("models").Activity} [options.activity]
     * @returns {FormData}
     */
    _buildFormData(formData, tmpURL, thread, composer, tmpId, options) {
        formData.append("thread_id", thread.id);
        formData.append("tmp_url", tmpURL);
        formData.append("thread_model", thread.model);
        formData.append("is_pending", Boolean(composer));
        formData.append("temporary_id", tmpId);
        if (options?.activity) {
            formData.append("activity_id", options.activity.id);
        }
        return formData;
    }

    /**
     * @param {{data: FormData, xhr: XMLHttpRequest, type: string, title: string, res_model: string}} upload
     * @param {number} tmpId
     * @param {import("models").Thread|undefined} thread
     * @param {string} tmpUrl
     * @returns {Object}
     */
    _makeAttachmentData(upload, tmpId, thread, tmpUrl) {
        const attachmentData = {
            id: tmpId,
            mimetype: upload.type,
            name: upload.title,
            resModel: upload.res_model,
            thread,
            extension: upload.title.split(".").pop(),
            uploading: true,
            tmpUrl,
        };
        return attachmentData;
    }
}

export const attachmentUploadService = {
    dependencies: ["file_upload", "mail.store", "notification"],
    /**
     * @param {import("@web/env").OdooEnv} env
     * @param {{ file_upload: any, "mail.store": any, notification: any }} services
     */
    start(env, services) {
        return new AttachmentUploadService(env, services);
    },
};

registry.category("services").add("mail.attachment_upload", attachmentUploadService);
