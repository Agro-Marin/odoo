// @ts-check
/** @odoo-module native */
import { fields } from "@mail/core/common/record";
import { Thread } from "@mail/core/common/thread_model";
import { makeLogger } from "@web/core/debug/debug_logger";
import { patch } from "@web/core/utils/patch";

const log = makeLogger("mail.thread");
/** @type {Partial<import("models").Thread> & ThisType<import("models").Thread>} */
const modelPatch = {
    setup() {
        super.setup();
        this.storeAsCounterChannel = fields.One("Store", {
            /** @this {import("models").Thread} */
            compute() {
                if (
                    this.isChannelKind &&
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
                log.logic("unpinned discuss thread replaced", () => ({
                    thread: this.localId,
                    replacement: newThread.localId,
                }));
                newThread.setAsDiscussThread();
            } else {
                this.store.discuss.thread = undefined;
            }
        }
    },
};
patch(Thread.prototype, modelPatch);
