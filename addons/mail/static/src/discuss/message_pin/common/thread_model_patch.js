// @ts-check
/** @odoo-module native */
import { fields } from "@mail/core/common/record";
import { Thread } from "@mail/core/common/thread_model";
import { rpc } from "@web/core/network";
import { patch } from "@web/core/utils/patch";
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
            this.pinnedMessagesState = "error";
            return;
        }
        this.store.insert(data);
        this.pinnedMessagesState = "loaded";
    },
};
patch(Thread.prototype, threadPatch);
