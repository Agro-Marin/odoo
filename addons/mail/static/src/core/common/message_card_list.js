/** @odoo-module native */
import { Message } from "@mail/core/common/message";
import { useVisible } from "@mail/utils/common/hooks";
import { Component, useSubEnv } from "@odoo/owl";
import { _t } from "@web/core/translation";
import { useService } from "@web/core/utils/hooks";
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
        useSubEnv({ messageCard: true });
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
        this.props.onClickJump?.();
        if (this.ui.isSmall || this.env.inChatWindow || this.env.inMeetingView) {
            this.env.pinMenu?.close();
            this.env.searchMenu?.close();
            this.env.inMeetingView?.openChat();
        }
        await new Promise((resolve) =>
            setTimeout(() => requestAnimationFrame(resolve)),
        );
        await this.env.messageHighlight?.highlightMessage(message, this.props.thread);
    }

    get emptyText() {
        return this.props.emptyText ?? _t("No messages found");
    }
}
