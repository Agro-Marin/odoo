/** @odoo-module native */
import { registerMessageAction } from "@mail/core/common/message_actions";
import { toRaw } from "@odoo/owl";
import { rpc } from "@web/core/network";
import { _t } from "@web/core/translation";

/** @typedef {import("@mail/core/common/message_actions").ActionParams} ActionParams */
registerMessageAction("set-new-message-separator", {
    /** @param {ActionParams} params */
    condition: ({ message, thread }) =>
        thread &&
        thread.self_member_id &&
        thread.eq(message.thread) &&
        !message.hasNewMessageSeparator &&
        message.persistent,
    icon: "fa-regular fa-eye-slash",
    name: _t("Mark as Unread"),
    /** @param {ActionParams} params */
    onSelected: ({ message: msg }) => {
        const message = toRaw(msg);
        const selfMember = message.thread?.self_member_id;
        if (selfMember) {
            selfMember.new_message_separator = message.id;
            selfMember.new_message_separator_ui = selfMember.new_message_separator;
        }
        message.thread.markedAsUnread = true;
        rpc("/discuss/channel/set_new_message_separator", {
            channel_id: message.thread.id,
            message_id: message.id,
        });
    },
    sequence: 70,
});
