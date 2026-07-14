/** @odoo-module native */
import { ACTION_TAGS } from "@mail/core/common/action";
import { registerThreadAction } from "@mail/core/common/thread_actions";
import { CallSettings } from "@mail/discuss/call/common/call_settings";
import { MeetingChat } from "@mail/discuss/call/common/meeting_chat";
import { _t } from "@web/core/l10n/translation";
registerThreadAction("meeting-chat", {
    actionPanelComponent: MeetingChat,
    badge: ({ thread }) => thread.isUnread,
    badgeIcon: ({ thread }) =>
        !thread.importantCounter && "fa-solid fa-circle text-700",
    badgeText: ({ thread }) => thread.importantCounter || undefined,
    condition: ({ owner }) => owner.env.inMeetingView,
    icon: "fa-solid fa-comments",
    name: _t("Chat"),
    panelOuterClass: "bg-100 border border-secondary",
    sequence: 30,
    toggle: true,
    tags: ({ thread }) => {
        const tags = [];
        if (thread.importantCounter) {
            tags.push(ACTION_TAGS.IMPORTANT_BADGE);
        }
        return tags;
    },
});
registerThreadAction("call", {
    condition: ({ store, thread }) =>
        thread?.allowCalls && !thread?.eq(store.rtc.channel),
    icon: "fa-solid fa-phone",
    name: ({ thread }) =>
        thread.rtc_session_ids.length > 0 ? _t("Join the Call") : _t("Start Call"),
    open: ({ store, thread }) => store.rtc.toggleCall(thread),
    sequence: 10,
    sequenceQuick: 30,
    tags: [ACTION_TAGS.SUCCESS, ACTION_TAGS.JOIN_LEAVE_CALL],
});
registerThreadAction("camera-call", {
    condition: ({ store, thread }) =>
        thread?.allowCalls && !thread?.eq(store.rtc.channel),
    icon: "fa-solid fa-video",
    name: ({ thread }) =>
        thread.rtc_session_ids.length > 0
            ? _t("Join the Call with Camera")
            : _t("Start Video Call"),
    open: ({ store, thread }) => store.rtc.toggleCall(thread, { camera: true }),
    sequence: 5,
    sequenceQuick: ({ owner }) => (owner.env.inDiscussApp ? 25 : 35),
    tags: [ACTION_TAGS.SUCCESS, ACTION_TAGS.JOIN_LEAVE_CALL],
});
registerThreadAction("call-settings", {
    actionPanelComponent: CallSettings,
    actionPanelComponentProps: () => ({ isCompact: true }),
    condition: ({ owner, store, thread }) =>
        thread?.allowCalls &&
        (owner.props.chatWindow?.isOpen || store.inPublicPage) &&
        !owner.isDiscussSidebarChannelActions,
    icon: "fa-solid fa-gear",
    name: _t("Call Settings"),
    sequence: 20,
    sequenceGroup: 30,
    toggle: true,
});
registerThreadAction("disconnect", {
    condition: ({ owner, store, thread }) =>
        store.rtc.selfSession?.in(thread?.rtc_session_ids) &&
        owner.isDiscussSidebarChannelActions,
    open: ({ store, thread }) => store.rtc.toggleCall(thread),
    icon: "fa-solid fa-phone",
    name: _t("Disconnect"),
    sequence: 30,
    sequenceGroup: 10,
    tags: [ACTION_TAGS.DANGER, ACTION_TAGS.JOIN_LEAVE_CALL],
});
