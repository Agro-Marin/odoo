/** @odoo-module native */
import { ACTION_TAGS } from "@mail/core/common/action";
import { registerThreadAction } from "@mail/core/common/thread_actions";
import { _t } from "@web/core/translation";

/** @typedef {import("@mail/core/common/thread_actions").ActionParams} ActionParams */
registerThreadAction("join-channel", {
    /**
     * A channel opened through a link or listed as a sub-channel is readable
     * without membership, so the roster has to be joinable on purpose --
     * posting is what used to join you, which is a poor way to find out.
     *
     * `discuss.channel` is not a nicety here: `self_member_id` and
     * `channel_type` are both added by the discuss patch, so on a chatter
     * thread they read `undefined` and the condition would hold. Chats and
     * groups have a fixed roster, and a livechat conversation is joined
     * through im_livechat's own `livechat_join_channel_needing_help`.
     *
     * @param {ActionParams} params
     */
    condition: ({ store, thread }) =>
        thread &&
        thread.model === "discuss.channel" &&
        !thread.self_member_id &&
        !["chat", "group", "livechat"].includes(thread.channel_type) &&
        Boolean(store.self_partner),
    icon: "fa-solid fa-right-to-bracket",
    name: _t("Join Channel"),
    /** @param {ActionParams} params */
    open: ({ store, thread }) =>
        store.env.services.orm.call("discuss.channel", "add_members", [[thread.id]], {
            partner_ids: [store.self_partner.id],
        }),
    sequence: 20,
    /** @param {ActionParams} params */
    sequenceGroup: ({ owner }) => (owner.isDiscussContent ? undefined : 5),
    tags: [ACTION_TAGS.SUCCESS],
});
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
