/** @odoo-module native */
import { registerThreadAction } from "@mail/core/common/thread_actions";
import { _t } from "@web/core/translation";

/** @typedef {import("@mail/core/common/thread_actions").ActionParams} ActionParams */
registerThreadAction("mark-all-read", {
    /** @param {ActionParams} params */
    condition: ({ owner, thread }) =>
        thread?.id === "inbox" && !owner.isDiscussSidebarChannelActions,
    /** @param {ActionParams} params */
    disabledCondition: ({ thread }) => thread.isEmpty,
    /** @param {ActionParams} params */
    open: ({ store }) =>
        store.env.services.orm.silent.call("mail.message", "mark_all_as_read"),
    sequence: 1,
    name: _t("Mark all read"),
});
registerThreadAction("unstar-all", {
    /** @param {ActionParams} params */
    condition: ({ owner, thread }) =>
        thread?.id === "starred" && !owner.isDiscussSidebarChannelActions,
    /** @param {ActionParams} params */
    disabledCondition: ({ thread }) => thread.isEmpty,
    /** @param {ActionParams} params */
    open: ({ store }) => store.unstarAll(),
    sequence: 2,
    name: _t("Unstar all"),
});
