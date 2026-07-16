/** @odoo-module native */
import { Message } from "@mail/core/common/message_model";
import { fields } from "@mail/core/common/record";
import { patch } from "@web/core/utils/patch";
/** @type {import("models").Message} */
const messagePatch = {
    setup() {
        super.setup();
        this.hasEveryoneSeen = fields.Attr(false, {
            /** @this {import("models").Message} */
            compute() {
                // kept as a member scan: lastMessageSeenByAllId is the min
                // over members that HAVE a seen id, so it is not equivalent
                // to "every member has seen" (a member with no seen id must
                // make this false). every() short-circuits.
                return this.thread?.membersThatCanSeen.every((m) => m.hasSeen(this));
            },
        });
        this.hasNewMessageSeparator = fields.Attr(false, {
            compute() {
                // compute for caching the value and not re-rendering all
                // messages when new_message_separator changes
                return this.thread?.self_member_id?.new_message_separator === this.id;
            },
        });
        this.hasSomeoneFetched = fields.Attr(false, {
            /** @this {import("models").Message} */
            compute() {
                if (this.isSelfAuthored && this.thread) {
                    // self-authored (the only displayed case): "someone other
                    // than me fetched it" is the thread-level max fetched id
                    // by others, O(1) vs scanning every member
                    return this.thread.maxFetchedMessageIdByOthers >= this.id;
                }
                return this.thread?.channel_member_ids.some(
                    (m) =>
                        // persona can be unset while the member's partner or
                        // guest is not inserted yet (computes run eagerly on
                        // insert): such a member cannot count as "fetched"
                        m.persona?.notEq(this.author) &&
                        m.fetched_message_id?.id >= this.id,
                );
            },
        });
        this.hasSomeoneSeen = fields.Attr(false, {
            /** @this {import("models").Message} */
            compute() {
                if (this.isSelfAuthored && this.thread) {
                    // self-authored (the only displayed case): "someone other
                    // than me saw it" is the thread-level max seen id by
                    // others, O(1) vs scanning every member
                    return this.thread.maxSeenMessageIdByOthers >= this.id;
                }
                return (
                    this.thread?.membersThatCanSeen
                        // persona can be unset while the member's partner or
                        // guest is not inserted yet: exclude such members
                        .filter((member) => member.persona?.notEq(this.author))
                        .some((m) => m.hasSeen(this))
                );
            },
        });
        this.isMessagePreviousToLastSelfMessageSeenByEveryone = fields.Attr(false, {
            /** @this {import("models").Message} */
            compute() {
                if (!this.thread?.lastSelfMessageSeenByEveryone) {
                    return false;
                }
                return this.id < this.thread.lastSelfMessageSeenByEveryone.id;
            },
        });
        /** @type {Promise<Thread>[]} @deprecated */
        this.mentionedChannelPromises = [];
        this.threadAsFirstUnread = fields.One("Thread", {
            inverse: "firstUnreadMessage",
        });
    },
    /** @returns {import("models").ChannelMember[]} */
    get channelMemberHaveSeen() {
        return this.thread.membersThatCanSeen.filter(
            (m) => m.hasSeen(this) && m.persona.notEq(this.author),
        );
    },
    /**
     * @override
     */
    async edit(
        body,
        attachments = [],
        { mentionedChannels = [], mentionedPartners = [], mentionedRoles = [] } = {},
    ) {
        return await super.edit(body, attachments, {
            mentionedChannels,
            mentionedPartners,
            mentionedRoles,
        });
    },
};
patch(Message.prototype, messagePatch);
