/** @odoo-module native */
import { fields } from "@mail/core/common/record";
import { Thread } from "@mail/core/common/thread_model";
import { patch } from "@web/core/utils/patch";
patch(Thread.prototype, {
    setup() {
        super.setup();

        /** @type {'loaded'|'loading'|'error'|undefined} */
        this.pinnedMessagesState = undefined;
        /**
         * Told by the server so the chatter can offer the panel without
         * fetching every pinned message first. Once the panel is open,
         * `pinnedMessages.length` is the live count.
         *
         * @type {boolean|undefined}
         */
        this.has_pinned_messages = undefined;
        this.pinnedMessages = fields.Many("mail.message", {
            inverse: "threadAsPinned",
            sort: (m1, m2) => {
                if (m1.pinned_at.equals(m2.pinned_at)) {
                    return m1.id - m2.id;
                }
                return m1.pinned_at < m2.pinned_at ? 1 : -1;
            },
        });
    },

    async fetchPinnedMessages() {
        if (["loaded", "loading"].includes(this.pinnedMessagesState)) {
            return;
        }
        this.pinnedMessagesState = "loading";
        try {
            await this.store.fetchStoreData("mixin.mail.thread", {
                thread_model: this.model,
                thread_id: this.id,
                request_list: ["pinned_messages"],
            });
        } catch {
            this.pinnedMessagesState = "error";
            return;
        }
        this.pinnedMessagesState = "loaded";
    },

    /**
     * Pinning is a plain toggle everywhere except a channel, where every
     * member sees the pin and a notification is posted: that one asks first.
     *
     * @param {import("models").Message} message
     */
    async setMessagePin(message, pinned) {
        await this.store.env.services.orm.call(this.model, "set_message_pin", [this.id], {
            message_id: message.id,
            pinned,
        });
    },
});
