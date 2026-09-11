// @ts-check
/** @odoo-module native */
import { DiscussCoreCommon } from "@mail/discuss/core/common/discuss_core_common_service";
import { applyCounterDelta } from "@mail/utils/common/counters";
import { patch } from "@web/core/utils/patch";
patch(DiscussCoreCommon.prototype, {
    /**
     * @param {import("models").Thread} thread
     * @param {{ id: number}} metadata
     */
    _handleNotificationChannelDelete(thread, metadata) {
        const { id: notifId } = metadata;
        const filteredStarredMessages = [];
        let starredCounter = 0;
        for (const msg of this.store.starred.messages) {
            if (!msg.thread?.eq(thread)) {
                filteredStarredMessages.push(msg);
            } else {
                starredCounter++;
            }
        }
        this.store.starred.messages =
            /** @type {typeof this.store.starred.messages} */ (
                /** @type {unknown} */ (filteredStarredMessages)
            );
        applyCounterDelta(this.store.starred, "counter", -starredCounter, {
            busId: notifId,
        });
        this.store.inbox.messages = /** @type {typeof this.store.inbox.messages} */ (
            /** @type {unknown} */ (
                this.store.inbox.messages.filter((msg) => !msg.thread?.eq(thread))
            )
        );
        applyCounterDelta(
            this.store.inbox,
            "counter",
            -thread.message_needaction_counter,
            { busId: notifId },
        );
        this.store.history.messages =
            /** @type {typeof this.store.history.messages} */ (
                /** @type {unknown} */ (
                    this.store.history.messages.filter((msg) => !msg.thread?.eq(thread))
                )
            );
        if (thread.eq(this.store.discuss.thread)) {
            this.store.discuss.thread = undefined;
        }
        return super._handleNotificationChannelDelete(thread, metadata);
    },
});
