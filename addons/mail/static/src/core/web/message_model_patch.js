/** @odoo-module native */
import { Message } from "@mail/core/common/message_model";
import { applyCounterDelta, snapshotCounter } from "@mail/utils/common/counters";
import { patch } from "@web/core/utils/patch";
/**
 * @type {Partial<import("models").Message> & ThisType<import("models").Message>}
 */
const messagePatch = {
    /** @param {import("models").Thread} thread */
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
