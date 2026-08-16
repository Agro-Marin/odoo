/** @odoo-module native */
import { registerThreadAction } from "@mail/core/common/thread_actions";
import { _t } from "@web/core/translation";

/** @typedef {import("@mail/core/common/thread_actions").ActionParams} ActionParams */
registerThreadAction("expand-discuss", {
    /** @param {ActionParams} params */
    condition: ({ owner, store, thread }) =>
        thread &&
        owner.props.chatWindow?.isOpen &&
        thread.model === "discuss.channel" &&
        !store.env.services.ui.isSmall &&
        !owner.isDiscussSidebarChannelActions,
    icon: "fa-solid fa-up-right-and-down-left-from-center",
    name: _t("Open in Discuss"),
    /** @param {ActionParams} params */
    open({ owner, store, thread }) {
        store.env.services.action.doAction(
            {
                type: "ir.actions.client",
                tag: "mail.action_discuss",
            },
            {
                clearBreadcrumbs: owner.env.services["home_menu"]?.hasHomeMenu,
                additionalContext: { active_id: thread.id },
            },
        );
    },
    sequence: 10,
    sequenceGroup: 5,
});
registerThreadAction("advanced-settings", {
    /** @param {ActionParams} params */
    condition: ({ owner, thread }) => thread && owner.isDiscussSidebarChannelActions,
    /** @param {ActionParams} params */
    open: ({ owner, store, thread }) => {
        store.env.services.action.doAction({
            type: "ir.actions.act_window",
            res_model: "discuss.channel",
            views: [[false, "form"]],
            res_id: thread.id,
            target: "current",
        });
    },
    icon: "fa-solid fa-gear",
    name: _t("Advanced Settings"),
    sequence: 20,
    sequenceGroup: 30,
});
