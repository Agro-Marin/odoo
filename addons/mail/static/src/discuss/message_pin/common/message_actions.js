/** @odoo-module native */
import { registerMessageAction } from "@mail/core/common/message_actions";
import { _t } from "@web/core/translation";

/** @typedef {import("@mail/core/common/message_actions").ActionParams} ActionParams */
registerMessageAction("pin", {
    /** @param {ActionParams} params */
    condition: ({ store, thread }) =>
        store.self_partner && thread?.model === "discuss.channel",
    icon: "fa-solid fa-thumbtack",
    /** @param {ActionParams} params */
    name: ({ message }) => (message.pinned_at ? _t("Unpin") : _t("Pin")),
    /** @param {ActionParams} params */
    onSelected: ({ message }) => message.pin(),
    sequence: 65,
});
