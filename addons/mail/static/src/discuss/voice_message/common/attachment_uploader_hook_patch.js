/** @odoo-module native */
import { AttachmentUploadService } from "@mail/core/common/attachment_upload_service";
import { patch } from "@web/core/utils/patch";
patch(AttachmentUploadService.prototype, {
    /**
     * @param {{data: FormData, type: string, title: string}} upload
     * @param {number} tmpId
     * @param {import("models").Thread|undefined} thread
     * @param {string} tmpUrl
     * @returns {Object}
     */
    _makeAttachmentData(upload, tmpId, thread, tmpUrl) {
        const attachmentData = super._makeAttachmentData(...arguments);
        if (upload.data.get("voice")) {
            attachmentData.voice_ids = [
                this.store["discuss.voice.metadata"].insert({ id: -1 }),
            ];
        }
        return attachmentData;
    },
    /**
     * @param {FormData} formData
     * @param {string} tmpURL
     * @param {import("models").Thread} thread
     * @param {import("models").Composer|undefined} composer
     * @param {number} tmpId
     * @param {Object} [options]
     * @param {boolean} [options.voice]
     * @returns {FormData}
     */
    _buildFormData(formData, tmpURL, thread, composer, tmpId, options) {
        super._buildFormData(...arguments);
        if (options?.voice) {
            formData.append("voice", true);
        }
        return formData;
    },
});
