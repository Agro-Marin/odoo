// @ts-check
/** @odoo-module native */
import { toRaw } from "@odoo/owl";
import { makeLogger } from "@web/core/debug/debug_logger";

const log = makeLogger("mail.thread");

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
        log.logic("markThreadAsReadIfAtBottom", () => ({ thread: thread.localId }));
        thread.markAsRead();
    }
}
