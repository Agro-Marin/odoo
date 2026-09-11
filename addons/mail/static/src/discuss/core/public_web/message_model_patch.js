// @ts-check
/** @odoo-module native */
import { Message } from "@mail/core/common/message_model";
import { fields } from "@mail/model/misc";
import { patch } from "@web/core/utils/patch";
/** @type {Partial<import("models").Message> & ThisType<import("models").Message>} */
const modelPatch = {
    setup() {
        super.setup();
        this.linkedSubChannel = fields.One("Thread", { inverse: "from_message_id" });
    },
};
patch(Message.prototype, modelPatch);
