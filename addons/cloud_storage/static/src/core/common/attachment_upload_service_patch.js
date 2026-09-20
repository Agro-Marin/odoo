/** @odoo-module native */
import { AttachmentUploadService } from "@mail/core/common/attachment_upload_service";

import { patch } from "@web/core/utils/patch";
import { session } from "@web/session";

patch(AttachmentUploadService.prototype, {
    setup(env, services) {
        super.setup(env, services);
        this.uploadingCloudFiles = new Map();
        window.addEventListener("beforeunload", () => {
            for (const { abort } of this.pendingUploads.values()) {
                abort?.();
            }
        });
    },

    async _processLoaded(thread, composer, { data, upload_info }, tmpId, def) {
        if (!upload_info) {
            super._processLoaded(...arguments);
            return;
        }
        const removeAttachment = () => {
            const { store_data, attachment_id } = data;
            this.store.insert(store_data);
            /** @type {import("models").Attachment} */
            const attachment = this.store["ir.attachment"].get(attachment_id);
            attachment.remove();
        };
        const file = this.uploadingCloudFiles.get(tmpId);
        try {
            const upload = this.fileUploadService.uploadToUrl(upload_info, file);
            this.pendingUploads.get(tmpId).abort = upload.abort;
            await upload;
        } catch (error) {
            if (!this.pendingUploads.has(tmpId)) {
                return;
            }
            removeAttachment();
            if (error.name !== "AbortError") {
                this.notificationService.add(error.message, { type: "danger" });
                def.resolve();
            }
            this._cleanupUploading(tmpId);
            return;
        }
        if (!this.pendingUploads.has(tmpId)) {
            return;
        }
        super._processLoaded(...arguments);
    },

    _cleanupUploading(tmpId) {
        super._cleanupUploading(tmpId);
        this.uploadingCloudFiles.delete(tmpId);
    },

    async _upload(thread, composer, file, options, tmpId, tmpURL) {
        if (
            session.cloud_storage_min_file_size !== undefined &&
            file.size > session.cloud_storage_min_file_size &&
            !session.cloud_storage_unsupported_models.includes(thread.model)
        ) {
            this.uploadingCloudFiles.set(tmpId, file);
            file = this.fileUploadService.placeholderFor(file);
            options = options
                ? { ...options, cloud_storage: true }
                : { cloud_storage: true };
        }
        return super._upload(thread, composer, file, options, tmpId, tmpURL);
    },

    _updateFormData(formData, tmpURL, thread, composer, tmpId, options) {
        super._updateFormData(...arguments);
        if (options?.cloud_storage) {
            formData.append("cloud_storage", true);
        }
        return formData;
    },
});
