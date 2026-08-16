/** @odoo-module native */
import { Component } from "@odoo/owl";
import { _t } from "@web/core/translation";

import { MessageCardList } from "./message_card_list.js";

const SEARCH_COUNT_CAP = 1000;
/**
 * @typedef {Object} Props
 * @property {import("models").Thread} thread
 * @property {ReturnType<import("@mail/core/common/message_search_hook").useMessageSearch>} messageSearch
 * @property {function} [onClickJump]
 */
export class SearchMessageResult extends Component {
    static template = "mail.SearchMessageResult";
    static components = { MessageCardList };
    static props = ["thread", "messageSearch", "onClickJump?"];

    get MESSAGE_FOUND() {
        if (this.props.messageSearch.messages.length === 0) {
            return false;
        }
        const count = this.props.messageSearch.count;
        if (count >= SEARCH_COUNT_CAP) {
            return _t("%s+ messages found", SEARCH_COUNT_CAP);
        }
        return _t("%s messages found", count);
    }

    onLoadMoreVisible() {
        const before = this.props.messageSearch?.messages
            ? Math.min(
                  ...this.props.messageSearch.messages.map((message) => message.id),
              )
            : false;
        this.props.messageSearch.search(before);
    }
}
