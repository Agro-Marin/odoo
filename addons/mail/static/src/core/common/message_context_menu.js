/** @odoo-module native */
import { Component, useRef } from "@odoo/owl";
import { Dropdown } from "@web/components/dropdown";
import { useForwardRefToParent, useService } from "@web/core/utils/hooks";

import { ActionList } from "./action_list.js";
import { useMessageActions } from "./message_actions.js";

export class MessageContextMenu extends Component {
    static template = "mail.MessageContextMenu";
    static components = { ActionList, Dropdown };
    static props = ["anchorRef", "dropdownState", "message", "thread?"];

    setup() {
        super.setup();
        useForwardRefToParent("anchorRef");
        this.store = useService("mail.store");
        this.anchor = useRef("anchorRef");
        this.isMessageContextMenu = true;
        this.messageActions = useMessageActions({
            message: () => this.props.message,
            thread: () => this.props.thread,
        });
    }
}
