/** @odoo-module native */
import { ActionPanel } from "@mail/core/common/action_panel";
import { Component, useState } from "@odoo/owl";
import { registry } from "@web/core/registry";
import { useAutofocus, useService } from "@web/core/utils/hooks";

const commandRegistry = registry.category("discuss.channel_commands");

export class LivechatCommandDialog extends Component {
    static template = "im_livechat.LivechatCommandDialog";
    static components = { ActionPanel };
    static props = [
        "thread",
        "close",
        "commandName",
        "placeholderText",
        "title",
        "icon",
    ];

    setup() {
        this.state = useState({ inputText: "" });
        this.store = useService("mail.store");
        useAutofocus();
    }

    onKeydown(ev) {
        if (ev.key === "Enter" && this.state.inputText.trim().length > 0) {
            this.executeCommand();
        }
    }

    executeCommand() {
        const command = commandRegistry.get(this.props.commandName, false);
        if (command) {
            this.props.thread.executeCommand(
                command,
                `/${this.props.commandName} ${this.state.inputText}`,
            );
            this.props.close();
        }
    }
}
