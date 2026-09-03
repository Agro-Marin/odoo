/** @odoo-module native */
import { Component } from "@odoo/owl";

/**
 * @typedef {Object} Props
 * @property {import("models").MailPoll} poll
 * @extends {Component<Props, import("@web/env").OdooEnv>}
 */
export class PollResult extends Component {
    static template = "mail.PollResult";
    static props = ["poll"];

    onClickViewPoll() {
        this.env.messageHighlight?.highlightMessage(
            this.props.poll.start_message_id,
            this.props.poll.start_message_id.thread,
        );
    }
}
