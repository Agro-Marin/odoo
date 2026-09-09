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
        const wasCountedById = new Map(
            messageIds.map((id) => {
                const message = this.store["mail.message"].get({ id });
                return [id, Boolean(message?.in(starredBox.messages))];
            }),
        );
        super._handleNotificationToggleStar(payload, metadata);
        for (const id of messageIds) {
            const message = this.store["mail.message"].get({ id });
            const wasCounted = wasCountedById.get(id);
            if (starred) {
                if (!wasCounted) {
                    applyCounterDelta(starredBox, "counter", 1, { busId: notifId });
                }
                if (message.thread) {
                    starredBox.messages.add(message);
                } else {
                    starredBox.isLoaded = false;
                }
            } else {
                if (wasCounted) {
                    applyCounterDelta(starredBox, "counter", -1, { busId: notifId });
                }
                starredBox.messages.delete(message);
            }
        }
    },
});
