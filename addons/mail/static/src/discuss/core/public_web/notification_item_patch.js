/** @odoo-module native */
import { NotificationItem } from "@mail/core/public_web/notification_item";
import { MessageSeenIndicator } from "@mail/discuss/core/common/message_seen_indicator";
import { patch } from "@web/core/utils/patch";
NotificationItem.components = { ...NotificationItem.components, MessageSeenIndicator };

/** @type {NotificationItem} */
const notificationItemPatch = {
    /** @returns {import("models").Message|undefined} */
    get previewedMessage() {
        return this.props.thread?.newestPersistentOfAllMessage;
    },
};
patch(NotificationItem.prototype, notificationItemPatch);
