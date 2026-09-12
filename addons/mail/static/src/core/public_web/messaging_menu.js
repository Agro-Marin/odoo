// @ts-check
/** @odoo-module native */
import { CountryFlag } from "@mail/core/common/country_flag";
import { ImStatus } from "@mail/core/common/im_status";
import { NotificationItem } from "@mail/core/public_web/notification_item";
import { useDiscussSystray } from "@mail/utils/common/hooks";
import { navigateIndex } from "@mail/utils/common/misc";
import {
    Component,
    onWillDestroy,
    useExternalListener,
    useRef,
    useState,
    useSubEnv,
} from "@odoo/owl";
import { Dropdown, useDropdownState } from "@web/components/dropdown";
import {
    hasTouch,
    isDisplayStandalone,
    isIOS,
} from "@web/core/browser/feature_detection";
import { getActiveHotkey } from "@web/core/browser/hotkeys";
import { makeLogger } from "@web/core/debug/debug_logger";
import { useLifecycleLog } from "@web/core/debug/logger_hooks";
import { registry } from "@web/core/registry";
import { _t } from "@web/core/translation";
import { useService } from "@web/core/utils/hooks";

import { DiscussContent } from "./discuss_content.js";

const log = makeLogger("mail.messaging_menu");

export class MessagingMenu extends Component {
    static components = {
        CountryFlag,
        DiscussContent,
        Dropdown,
        NotificationItem,
        ImStatus,
    };
    static props = [];
    static template = "mail.MessagingMenu";

    setup() {
        useLifecycleLog(log);
        super.setup();
        this.isIosPwa = isIOS() && isDisplayStandalone();
        this.store = useService("mail.store");
        this.hasTouch = hasTouch;
        this.ui = useService("ui");
        this.state = useState({
            /** @type {boolean|undefined} */
            searchOpen: undefined,
            activeIndex: null,
        });
        this.dropdown = useDropdownState();
        this.store.messagingMenu.dropdown = this.dropdown;
        onWillDestroy(() => (this.store.messagingMenu.dropdown = undefined));
        this.discussSystray = useDiscussSystray(this.dropdown);
        this.notificationList = useRef("notification-list");
        useSubEnv({ inMessagingMenu: { dropdown: this.dropdown } });

        useExternalListener(window, "keydown", this.onKeydown, true);
    }

    /**
     * @param {boolean} isMarkAsRead
     * @param {import("models").Thread} thread
     * @param {import("models").Message} [message]
     */
    onClickThread(isMarkAsRead, thread, message) {
        log.logic("onClickThread", () => ({
            thread: thread.localId,
            isMarkAsRead,
            messageId: message?.id,
            userNotification: message?.message_type === "user_notification",
        }));
        if (!isMarkAsRead) {
            if (message?.needaction && message.message_type === "user_notification") {
                this.store.inbox.highlightMessage = message;
                this.store.inbox.open();
                return;
            }
            thread.open({ focus: true, fromMessagingMenu: true, bypassCompact: true });
            this.dropdown.close();
            return;
        }
        this.markAsRead(thread);
    }

    /**
     * @param {boolean} isMarkAsRead
     * @param {import("models").Message} msg
     */
    onClickInboxMsg(isMarkAsRead, msg) {
        log.logic("onClickInboxMsg", () => ({ messageId: msg.id, isMarkAsRead }));
        if (!isMarkAsRead) {
            this.store.inbox.highlightMessage = msg;
            this.env.services.action.doAction({
                tag: "mail.action_discuss",
                type: "ir.actions.client",
                context: { active_id: "mail.box_inbox" },
            });
            return;
        }
        msg.setDone();
    }

    /** @param {import("models").Thread} thread */
    markAsRead(thread) {
        log.logic("markAsRead", () => ({
            thread: thread.localId,
            needaction: thread.needactionMessages.length,
        }));
        if (thread.needactionMessages.length > 0) {
            thread.markAllMessagesAsRead();
        }
    }

    /** @param {"first"|"last"|"previous"|"next"} direction */
    navigate(direction) {
        const targetId = navigateIndex(
            direction,
            this.state.activeIndex,
            this.notificationItems.length,
        );
        if (targetId === undefined) {
            return;
        }
        this.state.activeIndex = targetId;
        this.notificationItems[targetId]?.scrollIntoView({ block: "nearest" });
    }

    /** @param {KeyboardEvent} ev */
    onKeydown(ev) {
        if (!this.dropdown.isOpen) {
            return;
        }
        const hotkey = getActiveHotkey(ev);
        switch (hotkey) {
            case "enter":
                if (this.state.activeIndex === null) {
                    return;
                }
                this.notificationItems[this.state.activeIndex]?.click();
                break;
            case "tab":
                this.navigate(this.state.activeIndex === null ? "first" : "next");
                break;
            case "arrowup":
                this.navigate(this.state.activeIndex === null ? "first" : "previous");
                break;
            case "arrowdown":
                this.navigate(this.state.activeIndex === null ? "first" : "next");
                break;
            default:
                return;
        }
        ev.preventDefault();
        ev.stopPropagation();
    }

    get notificationItems() {
        return this.notificationList.el?.children ?? [];
    }

    get threads() {
        return this.store.messagingMenu.threads;
    }

    get visibleStandaloneMessages() {
        const tab = this.store.discuss.activeTab;
        if (tab !== "notification") {
            return [];
        }
        if (this.store.discuss.searchTerm) {
            return [];
        }
        return this.store.standaloneInboxMessages;
    }

    /** @type {{ id: string, icon: string, label: string, sequence: number, counter?: number, channelHasUnread?: boolean }[]} */
    get _tabs() {
        return [
            {
                counter: this.store.discuss.chats.threadsWithCounter.length,
                icon: "oi oi-users",
                id: "chat",
                label: _t("Chats"),
                sequence: 20,
            },
            {
                channelHasUnread: Boolean(this.store.discuss.unreadChannels.length),
                counter: this.store.discuss.channels.threadsWithCounter.length,
                icon: "fa-solid fa-hashtag",
                id: "channel",
                label: _t("Channels"),
                sequence: 40,
            },
        ];
    }

    get tabs() {
        return this._tabs.sort(
            /**
             * @param {{sequence: number}} t1
             * @param {{sequence: number}} t2
             */
            (t1, t2) => t1.sequence - t2.sequence,
        );
    }

    /** @param {import("models").DiscussApp["activeTab"]} tabId */
    onClickNavTab(tabId) {
        if (this.store.discuss.activeTab === tabId) {
            return;
        }
        log.logic("onClickNavTab", () => ({
            from: this.store.discuss.activeTab,
            to: tabId,
        }));
        this.store.discuss.activeTab = tabId;
        if (
            this.store.discuss.activeTab === "inbox" &&
            (!this.store.discuss.thread || !this.store.discuss.thread.isMailbox)
        ) {
            this.store.inbox.setAsDiscussThread();
        }
        if (this.store.discuss.activeTab === "starred") {
            this.store.starred.setAsDiscussThread();
        }
        if (!["inbox", "starred"].includes(this.store.discuss.activeTab)) {
            this.store.discuss.thread = undefined;
        }
    }

    /**
     * @param {import("models").Thread} thread
     * @returns {boolean}
     */
    canUnpinItem(thread) {
        return thread.canUnpin && thread.self_member_id?.message_unread_counter === 0;
    }
}

registry
    .category("systray")
    .add("mail.messaging_menu", { Component: MessagingMenu }, { sequence: 25 });
