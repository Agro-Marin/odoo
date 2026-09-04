/** @odoo-module native */
import { rpc } from "@web/core/network/rpc";
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
    onSelected: ({ message }) =>
        rpc("/web/dataset/call_kw", {
            model: "mail.message",
            method: "action_read_aloud",
            args: [[message.id]],
            kwargs: {},
        }),
    sequence: 115,
});
