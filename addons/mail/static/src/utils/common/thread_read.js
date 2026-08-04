/** @odoo-module native */
import { toRaw } from "@odoo/owl";

/**
 * Mark `thread` as read when its view is scrolled to the bottom and it is
 * currently focused, unless some state says it must stay unread.
 *
 * Single owner of the guards: the composer-focus, thread-focus and
 * thread-scroll paths must not each duplicate a subset of them, or e.g. focus
 * plus scroll fire the mark-as-read RPC twice (`markingAsRead`).
 *
 * @param {import("models").Thread} thread
 */
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
