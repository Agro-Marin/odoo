/** @odoo-module native */
import { fields } from "@mail/core/common/record";
import { Thread } from "@mail/core/common/thread_model";
import { rpc } from "@web/core/network/rpc";
import { patch } from "@web/core/utils/patch";
patch(Thread.prototype, {
    setup() {
        super.setup();

        /** @type {'loaded'|'loading'|'error'|undefined} */
        this.pinnedMessagesState = undefined;
        this.pinnedMessages = fields.Many("mail.message", {
            compute() {
                return this.allMessages.filter((m) => m.pinned_at);
            },
            sort: (m1, m2) => {
                // pinned_at is a luxon DateTime: distinct objects are never
                // ===, so compare by value; equal timestamps tiebreak on id.
                if (m1.pinned_at.equals(m2.pinned_at)) {
                    return m1.id - m2.id;
                }
                return m1.pinned_at < m2.pinned_at ? 1 : -1;
            },
        });
    },

    async fetchPinnedMessages() {
        if (
            this.model !== "discuss.channel" ||
            ["loaded", "loading"].includes(this.pinnedMessagesState)
        ) {
            return;
        }
        this.pinnedMessagesState = "loading";
        let data;
        try {
            data = await rpc("/discuss/channel/pinned_messages", {
                channel_id: this.id,
            });
        } catch {
            // Surface the failure through the reactive state: both callers are
            // fire-and-forget, so a re-throw would reach no handler.
            this.pinnedMessagesState = "error";
            return;
        }
        this.store.insert(data);
        this.pinnedMessagesState = "loaded";
    },
});
