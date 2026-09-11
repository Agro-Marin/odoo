// @ts-check
/** @odoo-module native */
import { ResPartner } from "@mail/core/common/res_partner_model";
import { fields } from "@mail/model/misc";
import { patch } from "@web/core/utils/patch";
/** @type {Partial<import("models").ResPartner> & ThisType<import("models").ResPartner>} */
const modelPatch = {
    setup() {
        super.setup();
        this.currentRtcSession = fields.One("discuss.channel.rtc.session", {
            inverse: "partner_id",
        });
    },
};
patch(ResPartner.prototype, modelPatch);
