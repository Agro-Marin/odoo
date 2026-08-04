/** @odoo-module native */
import { Attachment } from "@mail/core/common/attachment_model";
import { fields } from "@mail/core/common/record";
import { patch } from "@web/core/utils/patch";
/** @type {import("models").Attachment} */
const attachmentPatch = {
    setup() {
        this.voice_ids = fields.Many("discuss.voice.metadata");
    },
    get isViewable() {
        return !this.voice && super.isViewable;
    },
    delete() {
        // only clear for the ACTIVE player's own attachment: clearing on any
        // voice attachment breaks cross-player exclusivity, since the next play
        // would no longer pause the one still playing.
        const voiceService = this.store.env.services["discuss.voice_message"];
        if (this.voice && voiceService.activePlayer?.props.attachment.eq(this)) {
            voiceService.activePlayer = null;
        }
        super.delete(...arguments);
    },
    onClickAttachment(attachment) {
        if (!attachment.voice) {
            super.onClickAttachment(attachment);
        }
    },
    get voice() {
        return this.voice_ids.length > 0;
    },
};
patch(Attachment.prototype, attachmentPatch);
