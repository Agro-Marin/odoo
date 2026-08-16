/** @odoo-module native */
import { toRaw } from "@odoo/owl";

/** @param {import("models").Thread} thread */
export function markThreadAsReadIfAtBottom(thread) {
    thread = toRaw(thread);
    if (
        thread.scrollTop === "bottom" &&
        thread.isFocused &&
        !thread.scrollUnread &&
        !thread.markedAsUnread &&
        !thread.markingAsRead
    ) {
        thread.markAsRead();
    }
}
