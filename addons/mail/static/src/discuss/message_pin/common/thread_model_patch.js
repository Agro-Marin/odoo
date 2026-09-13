// @ts-check
/** @odoo-module native */
import { fields } from "@mail/core/common/record";
import { Thread } from "@mail/core/common/thread_model";
import { makeLogger } from "@web/core/debug/debug_logger";
import { rpc } from "@web/core/network";
import { patch } from "@web/core/utils/patch";

const log = makeLogger("mail.message.pin");
/** @type {Partial<import("models").Thread>} */
const threadPatch = {
    setup() {
        super.setup();

        /** @type {'loaded'|'loading'|'error'|undefined} */
        this.pinnedMessagesState = undefined;
        this.pinnedMessages = fields.Many("mail.message", {
            /** @this {import("models").Thread} */
            compute() {
                return this.allMessages.filter((m) => Boolean(m.pinned_at));
            },
            sort: (m1, m2) => {
                if (m1.pinned_at.equals(m2.pinned_at)) {
                    return Number(m1.id) - Number(m2.id);
                }
                return m1.pinned_at < m2.pinned_at ? 1 : -1;
            },
        });
    },

    async fetchPinnedMessages() {
        if (
            !this.isChannelKind ||
            ["loaded", "loading"].includes(this.pinnedMessagesState)
        ) {
            return;
        }
        this.pinnedMessagesState = "loading";
        let data;
        const endFetch = log.perf("fetchPinnedMessages");
        try {
            data = await rpc("/discuss/channel/pinned_messages", {
                channel_id: this.id,
            });
        } catch {
            endFetch({ thread: this.localId, failed: true });
            this.pinnedMessagesState = "error";
            return;
        }
        endFetch({ thread: this.localId, models: Object.keys(data || {}) });
        this.store.insert(data);
        this.pinnedMessagesState = "loaded";
    },
};
patch(Thread.prototype, threadPatch);
