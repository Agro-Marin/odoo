// @ts-check
/** @odoo-module native */
import { Thread } from "@mail/core/common/thread";
import { markThreadAsReadIfAtBottom } from "@mail/utils/common/thread_read";
import { toRaw } from "@odoo/owl";
import { makeLogger } from "@web/core/debug/debug_logger";
import { _t } from "@web/core/translation";
import { patch } from "@web/core/utils/patch";

const log = makeLogger("mail.thread.ui");
/** @type {Partial<Thread> & ThisType<Thread>} */
const threadPatch = {
    /** @param {import("models").Thread} thread */
    applyScrollContextually(thread) {
        if (thread.self_member_id && thread.scrollUnread) {
            if (thread.firstUnreadMessage) {
                const messageEl = this.refByMessageId.get(
                    thread.firstUnreadMessage.id,
                )?.el;
                if (!messageEl) {
                    return;
                }
                const messageCenter =
                    messageEl.offsetTop -
                    this.scrollableRef.el.offsetHeight / 2 +
                    messageEl.offsetHeight / 2;
                this.setScroll(messageCenter);
            } else {
                const scrollTop =
                    this.props.order === "asc"
                        ? this.scrollableRef.el.scrollHeight -
                          this.scrollableRef.el.clientHeight
                        : 0;
                this.setScroll(scrollTop);
            }
            thread.scrollUnread = false;
            markThreadAsReadIfAtBottom(thread);
        } else {
            super.applyScrollContextually(...arguments);
        }
    },
    fetchMessages() {
        if (this.props.thread.self_member_id && this.props.thread.scrollUnread) {
            log.logic("fetchMessages around new message separator", () => ({
                thread: this.props.thread.localId,
                separator: this.props.thread.self_member_id.new_message_separator,
            }));
            toRaw(this.props.thread).loadAround(
                this.props.thread.self_member_id.new_message_separator,
            );
        } else {
            super.fetchMessages();
        }
    },
    get newMessageBannerText() {
        if (this.props.thread.self_member_id?.message_unread_counter > 1) {
            return _t(
                "%s new messages",
                this.props.thread.self_member_id.message_unread_counter,
            );
        }
        return _t("1 new message");
    },
    async onClickUnreadMessagesBanner() {
        log.logic("onClickUnreadMessagesBanner", () => ({
            thread: this.props.thread.localId,
            separator: this.props.thread.self_member_id.new_message_separator_ui,
        }));
        await this.props.thread.loadAround(
            this.props.thread.self_member_id.new_message_separator_ui,
        );
        this.messageHighlight?.highlightMessage(
            this.props.thread.firstUnreadMessage,
            this.props.thread,
        );
    },
};
patch(Thread.prototype, threadPatch);
