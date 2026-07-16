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
                if (m1.pinned_at === m2.pinned_at) {
                    return m1.id - m2.id;
                }
                return m1.pinned_at < m2.pinned_at ? 1 : -1;
            },
        });
    },

    /**
     * @param {import("models").Thread} channel
     */
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
            // Surface the failure via the reactive state (the panel renders an
            // error/retry UI from `pinnedMessagesState`). Both callers invoke
            // this fire-and-forget, so re-throwing only produced an unhandled
            // rejection and never reached a handler.
            this.pinnedMessagesState = "error";
            return;
        }
        this.store.insert(data);
        this.pinnedMessagesState = "loaded";
    },
});
