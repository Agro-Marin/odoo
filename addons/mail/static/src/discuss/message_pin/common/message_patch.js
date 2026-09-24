// @ts-check
/** @odoo-module native */
import { Message } from "@mail/core/common/message";
import { useMailContext } from "@mail/utils/common/mail_context";
import { patch } from "@web/core/utils/patch";
patch(Message.prototype, {
    setup() {
        super.setup(...arguments);
        this.mailContext = useMailContext();
    },

    get isAlignedRight() {
        return !this.mailContext.messageCard && super.isAlignedRight;
    },
    get shouldDisplayAuthorName() {
        if (this.mailContext.messageCard) {
            return true;
        }
        return super.shouldDisplayAuthorName;
    },
});
