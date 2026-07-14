/** @odoo-module native */
import { toRaw } from "@odoo/owl";

/**
 * Mark `thread` as read when its view is scrolled to the bottom and it is
 * currently focused, unless some state says it must stay unread.
 *
 * Single owner of the guards: composer focus, thread focus and thread scroll
 * used to each duplicate a drifted subset of them (e.g. the focus paths missed
 * the in-flight `markingAsRead` guard, so focus + scroll could fire the
 * mark-as-read RPC twice).
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
