/** @odoo-module native */
import { MailCoreCommon } from "@mail/core/common/mail_core_common_service";
import { patch } from "@web/core/utils/patch";
patch(MailCoreCommon.prototype, {
    _handleNotificationToggleStar(payload, metadata) {
        const { id: notifId } = metadata;
        const { message_ids: messageIds, starred } = payload;
        const starredBox = this.store.starred;
        // capture pre-update state: the base handler overwrites
        // message.starred, and an optimistic local update (unstarAll) may
        // already have applied this very change — only actual transitions may
        // move the counter, else the echoed notification double-counts.
        // Unknown messages (undefined) still count: the snapshot counter
        // includes messages that are not loaded locally.
        const wasStarredById = new Map(
            messageIds.map((id) => [
                id,
                this.store["mail.message"].get({ id })?.starred,
            ]),
        );
        super._handleNotificationToggleStar(payload, metadata);
        for (const id of messageIds) {
            const message = this.store["mail.message"].get({ id });
            const wasStarred = wasStarredById.get(id);
            if (starred) {
                if (notifId > starredBox.counter_bus_id && wasStarred !== true) {
                    starredBox.counter++;
                }
                starredBox.messages.add(message);
            } else {
                if (notifId > starredBox.counter_bus_id && wasStarred !== false) {
                    starredBox.counter--;
                }
                starredBox.messages.delete(message);
            }
        }
    },
});
