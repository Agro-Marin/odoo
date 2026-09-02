/** @odoo-module native */
import { Composer } from "@mail/core/common/composer";
import { useMessageSearch } from "@mail/core/common/message_search_hook";
import { Thread } from "@mail/core/common/thread";
import { useThreadActions } from "@mail/core/common/thread_actions";
import { Call } from "@mail/discuss/call/common/call";
import { CallActionList } from "@mail/discuss/call/common/call_action_list";
import { ChannelInvitation } from "@mail/discuss/core/common/channel_invitation";
import {
    inDiscussCallViewProps,
    useInDiscussCallView,
    useMessageScrolling,
} from "@mail/utils/common/hooks";
import {
    Component,
    onMounted,
    onWillUnmount,
    useChildSubEnv,
    useSubEnv,
} from "@odoo/owl";
import { Dropdown } from "@web/components/dropdown";
import { useHotkey } from "@web/core/hotkeys/hotkey_hook";
import { useService } from "@web/core/utils/hooks";

import { MeetingSideActions } from "./meeting_side_actions.js";

/** @typedef {"chat"|"invite"} MeetingPanel */
/**
 * @typedef {Object} Props
 * @property {ThreadActionDefinition.id} [autoOpenAction]
 * @extends {Component<Props, import("@web/env").OdooEnv>}
 */
export class Meeting extends Component {
    static template = "mail.Meeting";
    static props = ["autoOpenAction?", ...inDiscussCallViewProps];
    static components = {
        Call,
        CallActionList,
        ChannelInvitation,
        Composer,
        Dropdown,
        MeetingSideActions,
        Thread,
    };

    setup() {
        this.store = useService("mail.store");
        this.ui = useService("ui");
        this.rtc = useService("discuss.rtc");
        onMounted(() => {
            if (this.props.autoOpenAction) {
                this.threadActions.actions
                    .find((a) => a.id === this.props.autoOpenAction)
                    ?.onSelected();
            }
        });
        useInDiscussCallView();
        useSubEnv({
            inMeetingView: {
                openChat: () =>
                    this.threadActions.actions
                        .find((action) => action.id === "meeting-chat")
                        ?.open(),
            },
        });
        this.threadActions = useThreadActions({ thread: () => this.thread });
        this.messageHighlight = useMessageScrolling();
        this.messageSearch = useMessageSearch(this.thread);
        useChildSubEnv({
            closeActionPanel: () => this.threadActions.activeAction?.close(),
            messageHighlight: this.messageHighlight,
            messageSearch: this.messageSearch,
        });
        onMounted(() => (this.store.meetingViewOpened = true));
        onWillUnmount(() => (this.store.meetingViewOpened = false));
        useHotkey("escape", () => this.onEscape());
    }

    get thread() {
        return this.store.rtc.channel;
    }

    /**
     * Peel the meeting one layer at a time, the way the chat window already
     * does it (`chat_window.js:123`): the open side panel first, the fullscreen
     * view itself last. Nothing else exits this view -- `enterFullscreen`
     * passes `keepBrowserHeader: true`, so `mail_fullscreen.js` never calls
     * `requestFullscreen()` and the browser's own Escape does not apply.
     */
    onEscape() {
        if (this.threadActions.activeAction) {
            this.threadActions.activeAction.close();
            return;
        }
        if (this.rtc.state.isFullscreen) {
            this.rtc.exitFullscreen();
        }
    }
}
