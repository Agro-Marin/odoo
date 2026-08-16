/** @odoo-module native */
import { registry } from "@web/core/registry";
import { _t } from "@web/core/translation";
const commandRegistry = registry.category("discuss.channel_commands");

/**
 * @typedef {Object} ChannelCommand
 * @property {string} methodName
 * @property {string} help
 * @property {string[]} [channel_types]
 * @property {number} [id]
 * @property {(params: { store: import("models").Store, thread: import("models").Thread, }) => boolean} [condition]
 */

commandRegistry
    .add("help", {
        /**
         * @param {Object} params
         * @param {import("models").Store} params.store
         * @param {import("models").Thread} params.thread
         * @returns {boolean}
         */
        condition: ({ store, thread }) =>
            store.self_partner && !store.self_partner.main_user_id.share,
        help: _t("Show a helper message"),
        methodName: "execute_command_help",
    })
    .add("leave", {
        /**
         * @param {Object} params
         * @param {import("models").Store} params.store
         * @param {import("models").Thread} params.thread
         * @returns {boolean}
         */
        condition: ({ store, thread }) =>
            store.self_partner && !store.self_partner.main_user_id.share,
        help: _t("Leave this channel"),
        methodName: "execute_command_leave",
    })
    .add("who", {
        /**
         * @param {Object} params
         * @param {import("models").Store} params.store
         * @param {import("models").Thread} params.thread
         * @returns {boolean}
         */
        condition: ({ store, thread }) =>
            store.self_partner && !store.self_partner.main_user_id.share,
        channel_types: ["channel", "chat", "group"],
        help: _t("List users in the current channel"),
        methodName: "execute_command_who",
    });
