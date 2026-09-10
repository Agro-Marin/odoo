/** @odoo-module native */
import { AttachmentUploadService } from "@mail/core/common/attachment_upload_service";
import { patch } from "@web/core/utils/patch";

patch(AttachmentUploadService.prototype, {
    _updateFormData(formData, file, thread, composer, tmpId, options) {
        super._updateFormData(...arguments);
        if (thread.rpcParams.hash && thread.rpcParams.pid) {
            formData.append("hash", thread.rpcParams.hash);
            formData.append("pid", thread.rpcParams.pid);
        }
        if (thread.rpcParams.token) {
            formData.append("token", thread.rpcParams.token);
        }
        return formData;
    },
});
