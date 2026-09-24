// @ts-check
/** @odoo-module native */
import { ActionPanel } from "@mail/core/common/action_panel";
import { SearchMessageInput } from "@mail/core/common/search_message_input";
import { SearchMessageResult } from "@mail/core/common/search_message_result";
import { useMailContext } from "@mail/utils/common/mail_context";
import { Component, onWillUpdateProps } from "@odoo/owl";
import { _t } from "@web/core/translation";
import { useService } from "@web/core/utils/hooks";

import { useMessageSearch } from "./message_search_hook.js";
/**
 * @typedef {Object} Props
 * @property {import("models").Thread} thread
 */
export class SearchMessagesPanel extends Component {
    static template = "mail.SearchMessagesPanel";
    static components = { ActionPanel, SearchMessageInput, SearchMessageResult };
    static props = ["thread"];

    setup() {
        super.setup();
        this.mailContext = useMailContext();
        this.store = useService("mail.store");
        this.messageSearch =
            this.mailContext.messageSearch ?? useMessageSearch(this.props.thread);
        onWillUpdateProps(
            /** @param {{thread: import("models").Thread}} nextProps */ (nextProps) => {
                if (this.props.thread.notEq(nextProps.thread)) {
                    this.mailContext.searchMenu?.close();
                }
            },
        );
    }

    get title() {
        return _t("Search Message");
    }
}
