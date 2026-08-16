/** @odoo-module native */
import { Thread } from "@mail/core/common/thread_model";
import { router } from "@web/core/browser/router";
import { _t } from "@web/core/translation";
import { patch } from "@web/core/utils/patch";
import { ConfirmationDialog } from "@web/ui/dialog";
patch(Thread.prototype, {
    /** @param {import("models").Message} message */
    async notifyMessageToUser(message) {
        const channel_notifications =
            this.self_member_id?.custom_notifications ||
            this.store.settings.channel_notifications;
        if (
            !this.self_member_id?.mute_until_dt &&
            !this.store.self.im_status?.includes("busy") &&
            (this.channel_type !== "channel" ||
                (this.channel_type === "channel" &&
                    (channel_notifications === "all" ||
                        (channel_notifications === "mentions" &&
                            message.isSelfMentioned))))
        ) {
            if (this.model === "discuss.channel" && this.inChathubOnNewMessage) {
                await this.store.chatHub.initPromise;
                let chatWindow = this.store.ChatWindow.get({ thread: this });
                if (!chatWindow) {
                    chatWindow = this.store.ChatWindow.insert({ thread: this });
                    if (
                        this.autoOpenChatWindowOnNewMessage &&
                        this.store.chatHub.opened.length < this.store.chatHub.maxOpened
                    ) {
                        chatWindow.open();
                    } else {
                        chatWindow.fold();
                    }
                }
            }
            if (this.notifyWhenOutOfFocus) {
                this.store.env.services["mail.out_of_focus"].notify(message, this);
            }
        }
    },
    get inChathubOnNewMessage() {
        return !this.store.discuss.isActive;
    },
    get autoOpenChatWindowOnNewMessage() {
        return false;
    },
    get notifyWhenOutOfFocus() {
        return true;
    },
    /** @param {boolean} pushState */
    setAsDiscussThread(pushState) {
        if (pushState === undefined) {
            pushState = this.notEq(this.store.discuss.thread);
        }
        this.store.discuss.thread = this;
        this.store.discuss.activeTab = !this.store.env.services.ui.isSmall
            ? "notification"
            : this.isMailbox
              ? this.store.self_partner?.main_user_id?.notification_type === "inbox"
                  ? "inbox"
                  : "starred"
              : ["chat", "group"].includes(this.channel_type)
                ? "chat"
                : "channel";
        if (pushState) {
            this.setActiveURL();
        }
        if (
            this.store.env.services.ui.isSmall &&
            !this.isMailbox &&
            !this.store.is_welcome_page_displayed
        ) {
            this.open({ focus: true });
        }
    },

    setActiveURL() {
        const activeId =
            typeof this.id === "string"
                ? `mail.box_${this.id}`
                : `discuss.channel_${this.id}`;
        router.pushState({ active_id: activeId });
        if (
            this.store.action_discuss_id &&
            this.store.env.services.action?.currentController?.action.id ===
                this.store.action_discuss_id
        ) {
            this.store.env.services.action.currentController.action.context.active_id =
                activeId;
        }
    },
    async unpin() {
        this.isLocallyPinned = false;
        if (this.eq(this.store.discuss.thread)) {
            router.replaceState({ active_id: undefined });
        }
        if (
            this.model === "discuss.channel" &&
            this.self_member_id?.is_pinned !== false
        ) {
            await this.store.env.services.orm.silent.call(
                "discuss.channel",
                "channel_pin",
                [this.id],
                { pinned: false },
            );
        }
    },
    /** @param {string} body */
    async askLeaveConfirmation(body) {
        await new Promise((resolve) => {
            this.store.env.services.dialog.add(ConfirmationDialog, {
                body: body,
                confirmLabel: _t("Leave Conversation"),
                confirm: resolve,
                cancel: () => {},
            });
        });
    },
});
