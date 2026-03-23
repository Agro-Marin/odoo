/** @odoo-module native */
import { Message } from "@mail/core/common/message";

import { SnailmailNotificationPopover } from "./snailmail_notification_popover.js";

Message.components = {
    ...Message.components,
    Popover: SnailmailNotificationPopover,
};
