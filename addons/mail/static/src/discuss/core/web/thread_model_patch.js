/** @odoo-module native */
import { fields } from "@mail/core/common/record";
import { Thread } from "@mail/core/common/thread_model";
import { patch } from "@web/core/utils/patch";
patch(Thread.prototype, {
    setup() {
        super.setup(...arguments);
        this.storeAsCounterChannel = fields.One("Store", {
            /** @this {import("models").Thread} */
            compute() {
                if (
                    this.model === "discuss.channel" &&
                    (this.message_needaction_counter > 0 ||
                        this.self_member_id?.message_unread_counter > 0)
                ) {
                    return this.store;
                }
            },
        });
    },
    onPinStateUpdated() {
        super.onPinStateUpdated();
        if (
            !this.displayToSelf &&
            !this.isLocallyPinned &&
            this.eq(this.store.discuss.thread)
        ) {
            if (this.store.discuss.isActive) {
                const newThread =
                    this.store.discuss.channels.threads.find(
                        (thread) => thread.displayToSelf || thread.isLocallyPinned,
                    ) || this.store.inbox;
                newThread.setAsDiscussThread();
            } else {
                this.store.discuss.thread = undefined;
            }
        }
    },
});
