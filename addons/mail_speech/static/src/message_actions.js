/** @odoo-module native */
import { _t } from "@web/core/translation";

import { registerMessageAction } from "@mail/core/common/message_actions";

registerMessageAction("read-aloud", {
    /** @param {Object} params */
    condition: ({ message, store }) =>
        message.message_type === "comment" &&
        !message.isEmpty &&
        !message.attachment_ids?.some((attachment) => attachment.voice) &&
        store.self?.isInternalUser,
    icon: "fa-solid fa-volume-up",
    name: _t("Read aloud"),
    /** @param {Object} params */
    onSelected: ({ message, store }) =>
        store.env.services.orm.call("mail.message", "action_read_aloud", [
            [message.id],
        ]),
    sequence: 115,
});
