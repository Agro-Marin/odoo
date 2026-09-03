/** @odoo-module native */
import { Message } from "@mail/core/common/message";
import { MessageSeenIndicator } from "@mail/discuss/core/common/message_seen_indicator";
import { patch } from "@web/core/utils/patch";
Message.components = { ...Message.components, MessageSeenIndicator };

/** @type {Message} */
const messagePatch = {
    // Thin delegate to the model: the rule itself lives on `Message` so that
    // the message previews (chat bubble, messaging menu) can ask it too. It
    // stays a component getter because downstream modules override it here to
    // add their own veto.
    get showSeenIndicator() {
        return this.props.message.showSeenIndicator(this.props.thread);
    },
};
patch(Message.prototype, messagePatch);
