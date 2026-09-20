// @ts-check
/** @odoo-module native */
import { makeLogger } from "@web/core/debug/debug_logger";
import { registry } from "@web/core/registry";
import { _t } from "@web/core/translation";
import { Deferred } from "@web/core/utils/concurrency";

/** @typedef {{data: FormData, xhr: XMLHttpRequest, type: string, title: string, res_model: string}} Upload */
/**
 * @typedef {Object} PendingUpload
 * @property {(() => void)|undefined} abort
 * @property {{attachments: import("models").Attachment[]}|undefined} composer
 * @property {Deferred<import("models").Attachment | undefined>} deferred
 * @property {import("models").Thread} thread
 * @property {string} tmpUrl
 */

const log = makeLogger("mail.attachment_upload");

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
        /** @type {Map<number, PendingUpload>} */
        this.pendingUploads = new Map();
        for (const [event, handler] of /** @type {const} */ ([
            ["FILE_UPLOAD_ADDED", this._onUploadAdded],
            ["FILE_UPLOAD_LOADED", this._onUploadLoaded],
            ["FILE_UPLOAD_ERROR", this._onUploadError],
        ])) {
            this.fileUploadService.bus.addEventListener(
                event,
                /** @param {CustomEvent<{upload: Upload}>} ev */
                ({ detail: { upload } }) => {
                    const tmpId = parseInt(
                        /** @type {string} */ (upload.data.get("temporary_id")),
                    );
                    if (this.pendingUploads.has(tmpId)) {
                        handler.call(this, upload, tmpId);
                    }
                },
            );
        }
    }

    /**
     * @param {Upload} upload
     * @param {number} tmpId
     */
    _onUploadAdded(upload, tmpId) {
        const pending = this.pendingUploads.get(tmpId);
        const { thread, composer } = pending;
        log.pipeline("upload added", () => ({
            tmpId,
            thread: thread?.localId,
            composer: Boolean(composer),
        }));
        const tmpUrl = /** @type {string} */ (upload.data.get("tmp_url"));
        pending.abort = upload.xhr.abort.bind(upload.xhr);
        const attachment = this.store["ir.attachment"].insert(
            this._makeAttachmentData(
                upload,
                tmpId,
                composer ? undefined : thread,
                tmpUrl,
            ),
        );
        composer?.attachments.push(attachment);
    }

    /**
     * @param {Upload} upload
     * @param {number} tmpId
     */
    _onUploadLoaded(upload, tmpId) {
        const response = this._parseUploadResponse(upload, tmpId);
        log.pipeline("upload loaded", () => ({ tmpId, ok: Boolean(response) }));
        if (!response) {
            return;
        }
        const { thread, composer, deferred } = this.pendingUploads.get(tmpId);
        this._processLoaded(thread, composer, response, tmpId, deferred);
    }

    /**
     * @param {Upload} upload
     * @param {number} tmpId
     */
    _onUploadError(upload, tmpId) {
        log.pipeline("upload error", () => ({ tmpId }));
        this.pendingUploads.get(tmpId).deferred.resolve();
        this._cleanupUploading(tmpId);
    }

    /**
     * @param {Upload} upload
     * @param {number} tmpId
     * @returns {Object|undefined}
     */
    _parseUploadResponse(upload, tmpId) {
        if (upload.xhr.status === 413) {
            return this._abandonUpload(tmpId, _t("File too large"));
        }
        if (upload.xhr.status !== 200) {
            return this._abandonUpload(tmpId, _t("Server error"));
        }
        let response;
        try {
            response = JSON.parse(upload.xhr.response);
        } catch {
            return this._abandonUpload(tmpId, _t("Server error"));
        }
        if (response.error) {
            return this._abandonUpload(tmpId, response.error);
        }
        return response;
    }

    /**
     * @param {number} tmpId
     * @param {string} message
     */
    _abandonUpload(tmpId, message) {
        log.logic("upload abandoned", () => ({ tmpId, message }));
        this.notificationService.add(message, { type: "danger" });
        this.pendingUploads.get(tmpId).deferred.resolve();
        this._cleanupUploading(tmpId);
    }

    /**
     * @param {import("models").Thread} thread
     * @param {{attachments: import("models").Attachment[]}|undefined} composer
     * @param {{data: {store_data: Object, attachment_id: number}}} response
     * @param {number} tmpId
     * @param {import("@web/core/utils/concurrency").Deferred} def
     */
    _processLoaded(thread, composer, { data }, tmpId, def) {
        const { store_data, attachment_id } = data;
        this.store.insert(store_data);
        /** @type {import("models").Attachment} */
        const attachment = this.store["ir.attachment"].get(attachment_id);
        log.pipeline("upload processed", () => ({
            tmpId,
            attachmentId: attachment_id,
            thread: thread?.localId,
            composer: Boolean(composer),
        }));
        if (composer) {
            const index = composer.attachments.findIndex(({ id }) => id === tmpId);
            if (index >= 0) {
                composer.attachments[index] = attachment;
            } else {
                composer.attachments.push(attachment);
            }
        }
        def.resolve(attachment);
        this._cleanupUploading(tmpId);
    }

    /** @param {number} tmpId */
    _cleanupUploading(tmpId) {
        const pending = this.pendingUploads.get(tmpId);
        this.pendingUploads.delete(tmpId);
        if (pending?.tmpUrl) {
            URL.revokeObjectURL(pending.tmpUrl);
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
        const pending = this.pendingUploads.get(attachment.id);
        log.logic("unlink", () => ({
            attachmentId: attachment.id,
            uploading: Boolean(pending),
        }));
        if (pending) {
            this._cleanupUploading(attachment.id);
            pending.deferred.resolve();
            pending.abort?.();
            return;
        }
        await attachment.remove();
    }

    /**
     * @param {import("models").Thread} thread
     * @param {{attachments: import("models").Attachment[]}|undefined} composer
     * @param {File} file
     * @param {Object} [options]
     * @param {import("models").Activity} [options.activity]
     * @returns {Promise<import("models").Attachment|undefined>}
     */
    async upload(thread, composer, file, options) {
        const tmpId = this.nextId--;
        const tmpURL = URL.createObjectURL(file);
        log.logic("upload", () => ({
            tmpId,
            name: file.name,
            size: file.size,
            type: file.type,
            thread: thread?.localId,
        }));
        return this._upload(thread, composer, file, options, tmpId, tmpURL);
    }

    /**
     * @param {import("models").Thread} thread
     * @param {{attachments: import("models").Attachment[]}|undefined} composer
     * @param {File} file
     * @param {Object | undefined} options
     * @param {number} tmpId
     * @param {string} tmpURL
     * @returns {Promise<import("models").Attachment|undefined>}
     */
    async _upload(thread, composer, file, options, tmpId, tmpURL) {
        /** @type {Deferred<import("models").Attachment | undefined>} */
        const uploadDoneDeferred = new Deferred();
        this.pendingUploads.set(tmpId, {
            abort: undefined,
            composer,
            deferred: uploadDoneDeferred,
            thread,
            tmpUrl: tmpURL,
        });
        const endUpload = log.perf("upload");
        uploadDoneDeferred.then((attachment) =>
            endUpload({ tmpId, attachmentId: attachment?.id, size: file.size }),
        );
        await this.fileUploadService
            .upload(this.getUploadURL(thread), [file], {
                /** @param {FormData} formData */
                buildFormData: (formData) => {
                    this._updateFormData(
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
     * @param {FormData} formData
     * @param {string} tmpURL
     * @param {import("models").Thread} thread
     * @param {{attachments: import("models").Attachment[]}|undefined} composer
     * @param {number} tmpId
     * @param {Object} [options]
     * @param {import("models").Activity} [options.activity]
     * @returns {FormData}
     */
    _updateFormData(formData, tmpURL, thread, composer, tmpId, options) {
        formData.append("thread_id", String(thread.id));
        formData.append("tmp_url", tmpURL);
        formData.append("thread_model", thread.model);
        formData.append("is_pending", String(Boolean(composer)));
        formData.append("temporary_id", String(tmpId));
        if (options?.activity) {
            formData.append("activity_id", String(options.activity.id));
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
