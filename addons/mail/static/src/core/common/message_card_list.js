// @ts-check
/** @odoo-module native */
import { Message } from "@mail/core/common/message";
import { useVisible } from "@mail/utils/common/hooks";
import { provideMailContext, useMailContext } from "@mail/utils/common/mail_context";
import { Component } from "@odoo/owl";
import { makeLogger } from "@web/core/debug/debug_logger";
import { _t } from "@web/core/translation";
import { useService } from "@web/core/utils/hooks";

const log = makeLogger("mail.message.search");
/**
 * @typedef {Object} Props
 * @property {string} [emptyText]
 * @property {import("models").Message[]} messages
 * @property {ReturnType<import('@mail/core/common/message_search_hook').useMessageSearch>} [messageSearch]
 * @property {function} [loadMore]
 * @property {string} mode
 * @property {function} [onClickJump]
 * @property {function} [onLoadMoreVisible]
 * @property {boolean} [showEmpty]
 * @property {import("models").Thread} thread
 * @extends {Component<Props, import("@web/env").OdooEnv>}
 */
export class MessageCardList extends Component {
    static components = { Message };
    static props = [
        "emptyText?",
        "messages",
        "messageSearch?",
        "loadMore?",
        "mode",
        "onClickJump?",
        "onLoadMoreVisible?",
        "showEmpty?",
        "thread",
    ];
    static template = "mail.MessageCardList";

    setup() {
        super.setup();
        this.ui = useService("ui");
        this.store = useService("mail.store");
        provideMailContext({ messageCard: true });
        this.mailContext = useMailContext();
        useVisible(
            "load-more",
            /** @param {boolean} isVisible */ (isVisible) => {
                if (isVisible) {
                    this.props.onLoadMoreVisible?.();
                }
            },
        );
    }

    /** @param {import("models").Message} message */
    async onClickJump(message) {
        log.logic("onClickJump", () => ({
            messageId: message.id,
            thread: this.props.thread?.localId,
            small: this.ui.isSmall,
            inChatWindow: Boolean(this.mailContext.inChatWindow),
            inMeetingView: Boolean(this.mailContext.inMeetingView),
        }));
        this.props.onClickJump?.();
        if (
            this.ui.isSmall ||
            this.mailContext.inChatWindow ||
            this.mailContext.inMeetingView
        ) {
            this.mailContext.pinMenu?.close();
            this.mailContext.searchMenu?.close();
            this.mailContext.inMeetingView?.openChat();
        }
        await new Promise((resolve) =>
            setTimeout(() => requestAnimationFrame(resolve)),
        );
        await this.mailContext.messageHighlight?.highlightMessage(
            message,
            this.props.thread,
        );
    }

    get emptyText() {
        return this.props.emptyText ?? _t("No messages found");
    }
}
