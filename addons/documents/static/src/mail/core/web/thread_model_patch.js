/** @odoo-module native */
import { getDocumentActionRequest } from "@documents/utils";
import { Thread } from "@mail/core/common/thread_model";
import { patch } from "@web/core/utils/patch";

import "@mail/core/web/thread_model_patch";

patch(Thread.prototype, {
    get openRecordActionRequest() {
        if (this.model === "documents.document" && this.id) {
            return getDocumentActionRequest(this.id);
        }
        return super.openRecordActionRequest;
    },
});
