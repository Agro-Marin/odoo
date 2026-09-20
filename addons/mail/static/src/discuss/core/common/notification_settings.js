// @ts-check
/** @odoo-module native */
import { ActionPanel } from "@mail/core/common/action_panel";
import { Component, xml } from "@odoo/owl";
import { Dropdown, DropdownItem } from "@web/components/dropdown";
import { makeLogger } from "@web/core/debug/debug_logger";
import { useService } from "@web/core/utils/hooks";
import { Dialog } from "@web/ui/dialog";

import { DiscussNotificationSettingsClientAction } from "./discuss_notification_settings_client_action.js";

const log = makeLogger("mail.settings");

class NotificationDialog extends Component {
    static props = ["close?"];
    static components = { Dialog, DiscussNotificationSettingsClientAction };
    static template = xml`
        <Dialog size="'md'" footer="false">
            <DiscussNotificationSettingsClientAction/>
        </Dialog>
    `;
}

export class NotificationSettings extends Component {
    static components = { ActionPanel, Dropdown, DropdownItem };
    static props = ["hasSizeConstraints?", "thread", "close?", "className?"];
    static template = "discuss.NotificationSettings";

    setup() {
        this.store = useService("mail.store");
        this.dialog = useService("dialog");
        this.ui = useService("ui");
    }

    /** @param {number} minutes */
    setMute(minutes) {
        log.logic("setMute", () => ({ thread: this.props.thread?.localId, minutes }));
        this.store.settings.setMuteDuration(minutes, this.props.thread);
        this.props.close?.();
    }

    onClickAllConversationsMuted() {
        this.dialog.add(NotificationDialog);
    }
}
