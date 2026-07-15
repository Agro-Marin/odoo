/** @odoo-module native */
import { Message } from "@mail/core/common/message_model";
import { applyCounterDelta, snapshotCounter } from "@mail/utils/common/counters";
import { patch } from "@web/core/utils/patch";
/** @type {import("models").Message} */
const messagePatch = {
    /** @param {import("models").Thread} thread the thread where the message is shown */
    canReplyAll(thread) {
        return this.canForward(thread) && !this.isNote;
    },
    /** @param {import("models").Thread} thread */
    canForward(thread) {
        if (!thread) {
            return false;
        }
        return (
            !(thread.isChannelKind || thread.isMailbox) &&
            ["comment", "email"].includes(this.message_type)
        );
    },
    async toggleStar() {
        // The "Starred" mailbox counter is moved by the echoed
        // `mail.message/toggle_star` notification, but only on an actual
        // starred transition (see mail_core_common_service_patch). The base
        // toggleStar's RPC result eagerly flips `starred`, so by the time that
        // notification arrives it sees no transition and the counter would
        // never move. Update the counter (and the box's message set)
        // optimistically here — like unstarAll — and let the notification's
        // guard dedupe it. Only relevant on the web layer, where `starred`
        // exists.
        const starredBox = this.store.starred;
        if (!starredBox) {
            return super.toggleStar(...arguments);
        }
        const willStar = !this.starred;
        const counterSnapshot = snapshotCounter(starredBox, "counter");
        this.starred = willStar;
        applyCounterDelta(starredBox, "counter", willStar ? 1 : -1);
        if (willStar) {
            starredBox.messages.add(this);
        } else {
            starredBox.messages.delete(this);
        }
        try {
            await super.toggleStar(...arguments);
        } catch (error) {
            // roll back the optimistic update (the snapshot is skipped if a
            // newer absolute counter snapshot landed in the meantime)
            this.starred = !willStar;
            counterSnapshot.restore();
            if (willStar) {
                starredBox.messages.delete(this);
            } else {
                starredBox.messages.add(this);
            }
            throw error;
        }
    },
};
patch(Message.prototype, messagePatch);
