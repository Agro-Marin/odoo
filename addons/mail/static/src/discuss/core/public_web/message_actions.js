/** @odoo-module native */
import { registerMessageAction } from "@mail/core/common/message_actions";
import { _t } from "@web/core/translation";

/** @typedef {import("@mail/core/common/message_actions").ActionParams} ActionParams */
registerMessageAction("create-or-view-thread", {
    /** @param {ActionParams} params */
    condition: ({ message, store, thread }) =>
        message.thread?.eq(thread) &&
        message.thread.hasSubChannelFeature &&
        store.self_partner?.main_user_id?.share === false,
    icon: "fa-regular fa-comments",
    /** @param {ActionParams} params */
    onSelected: ({ message }) => {
        if (message.linkedSubChannel) {
            message.linkedSubChannel.open({ focus: true });
        } else {
            message.thread.createSubChannel({ initialMessage: message });
        }
    },
    /** @param {ActionParams} params */
    name: ({ message }) =>
        message.linkedSubChannel ? _t("View Thread") : _t("Create Thread"),
    sequence: 75,
});
