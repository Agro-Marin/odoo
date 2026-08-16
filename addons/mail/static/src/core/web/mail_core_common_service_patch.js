/** @odoo-module native */
import { MailCoreCommon } from "@mail/core/common/mail_core_common_service";
import { applyCounterDelta } from "@mail/utils/common/counters";
import { patch } from "@web/core/utils/patch";
patch(MailCoreCommon.prototype, {
    /**
     * @param {{message_ids: number[], starred: boolean}} payload
     * @param {{id: number}} metadata
     */
    _handleNotificationToggleStar(payload, metadata) {
        const { id: notifId } = metadata;
        const { message_ids: messageIds, starred } = payload;
        const starredBox = this.store.starred;
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
                if (wasStarred !== true) {
                    applyCounterDelta(starredBox, "counter", 1, { busId: notifId });
                }
                starredBox.messages.add(message);
            } else {
                if (wasStarred !== false) {
                    applyCounterDelta(starredBox, "counter", -1, { busId: notifId });
                }
                starredBox.messages.delete(message);
            }
        }
    },
});
