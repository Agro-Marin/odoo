// @ts-check
/** @odoo-module native */
import { MailGuest } from "@mail/core/common/mail_guest_model";
import { fields } from "@mail/model/misc";
import { patch } from "@web/core/utils/patch";
/** @type {Partial<import("models").MailGuest> & ThisType<import("models").MailGuest>} */
const modelPatch = {
    setup() {
        super.setup();
        this.currentRtcSession = fields.One("discuss.channel.rtc.session", {
            inverse: "guest_id",
        });
    },
};
patch(MailGuest.prototype, modelPatch);
