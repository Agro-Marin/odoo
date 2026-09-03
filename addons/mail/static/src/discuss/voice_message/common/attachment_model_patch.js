/** @odoo-module native */
import { Attachment } from "@mail/core/common/attachment_model";
import { fields } from "@mail/core/common/record";
import { patch } from "@web/core/utils/patch";
/**
 * @type {Partial<import("models").Attachment> & ThisType<import("models").Attachment>}
 */
const attachmentPatch = {
    setup() {
        super.setup(...arguments);
        this.voice_ids = fields.Many("discuss.voice.metadata");
    },
    get isViewable() {
        return !this.voice && super.isViewable;
    },
    delete() {
        const voiceService = this.store.env.services["discuss.voice_message"];
        if (this.voice && voiceService.activePlayer?.props.attachment.eq(this)) {
            voiceService.activePlayer = null;
        }
        super.delete(...arguments);
    },
    get voice() {
        return this.voice_ids.length > 0;
    },
};
patch(Attachment.prototype, attachmentPatch);
