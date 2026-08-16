/** @odoo-module native */
import { registerThreadAction } from "@mail/core/common/thread_actions";
import { NO_MEMBERS_DEFAULT_OPEN_LS } from "@mail/core/public_web/discuss_app_model";
import { ChannelMemberList } from "@mail/discuss/core/common/channel_member_list";
import { SubChannelList } from "@mail/discuss/core/public_web/sub_channel_list";
import { useChildSubEnv } from "@odoo/owl";
import { browser } from "@web/core/browser/browser";
import { _t } from "@web/core/translation";
import { usePopover } from "@web/ui/popover";

/** @typedef {import("@mail/core/common/thread_actions").ActionParams} ActionParams */
registerThreadAction("show-threads", {
    actionPanelComponent: SubChannelList,
    /** @param {ActionParams} params */
    actionPanelComponentProps: ({ action }) => ({ close: () => action.close() }),
    /** @param {ActionParams} params */
    close: ({ action }) => action.popover?.close(),
    /** @param {ActionParams} params */
    condition: ({ owner, thread }) =>
        (thread?.hasSubChannelFeature ||
            thread?.parent_channel_id?.hasSubChannelFeature) &&
        !owner.isDiscussSidebarChannelActions,
    icon: "fa-regular fa-comments",
    name: _t("Threads"),
    /** @param {ActionParams} params */
    setup({ owner, store }) {
        if (owner.env.inDiscussApp && !store.env.isSmall) {
            this.popover = usePopover(SubChannelList, {
                onClose: () => this.close(),
                fixedPosition: true,
                popoverClass: this.panelOuterClass,
            });
        }
        useChildSubEnv({ subChannelMenu: { open: () => this.open() } });
    },
    /** @param {ActionParams} params */
    open({ owner, thread }) {
        const channel = thread?.parent_channel_id || thread;
        this.popover?.open(owner.root.el.querySelector(`[name="${this.id}"]`), {
            thread: channel,
        });
    },
    panelOuterClass: "bg-100 border border-secondary",
    /** @param {ActionParams} params */
    sequence: ({ owner }) => (owner.props.chatWindow ? 40 : 5),
    sequenceGroup: 10,
    toggle: true,
});
registerThreadAction("member-list", {
    actionPanelComponent: ChannelMemberList,
    /** @param {ActionParams} params */
    actionPanelComponentProps: ({ owner }) => ({
        /**
         * @param {Object} [options]
         * @param {boolean} [options.keepPrevious]
         */
        openChannelInvitePanel({ keepPrevious } = {}) {
            owner.threadActions.actions
                .find(({ id }) => id === "invite-people")
                ?.open({ keepPrevious });
        },
    }),
    /** @param {ActionParams} params */
    condition: ({ owner, thread }) =>
        thread?.hasMemberList &&
        (!owner.props.chatWindow || owner.props.chatWindow.isOpen) &&
        !owner.isDiscussSidebarChannelActions,
    panelOuterClass: "o-discuss-ChannelMemberList bg-inherit",
    icon: "oi oi-fw oi-users",
    name: _t("Members"),
    /** @param {ActionParams} params */
    close: ({ action, nextActiveAction, owner, store }) => {
        if (
            action.condition &&
            owner.env.inDiscussApp &&
            store.discuss?.shouldDisableMemberPanelAutoOpenFromClose(nextActiveAction)
        ) {
            browser.localStorage.setItem(NO_MEMBERS_DEFAULT_OPEN_LS, true);
            store.discuss._recomputeIsMemberPanelOpenByDefault++;
        }
    },
    /** @param {ActionParams} params */
    open: ({ owner, store }) => {
        if (owner.env.inDiscussApp) {
            browser.localStorage.removeItem(NO_MEMBERS_DEFAULT_OPEN_LS);
            store.discuss._recomputeIsMemberPanelOpenByDefault++;
        }
    },
    sequence: 30,
    sequenceGroup: 10,
    toggle: true,
});
