/** @odoo-module native */
import { fields } from "@mail/core/common/record";
import { Store } from "@mail/core/common/store_service";
import { AvatarCardPopover } from "@mail/discuss/web/avatar_card/avatar_card_popover";
import { compareDatetime } from "@mail/utils/common/misc";
import { patch } from "@web/core/utils/patch";
/** @type {import("models").Store} */
const StorePatch = {
    setup() {
        super.setup(...arguments);
        this.initChannelsUnreadCounter = 0;
        /**
         * Channels carrying unread or needaction messages, maintained by each
         * thread (@see Thread.storeAsCounterChannel). Scanning `Thread.records`
         * for them made `globalCounter` an observer of the counters of every
         * thread in the store, so it re-ran in full on every message that
         * changed one: measured at ~1.1ms per recompute with 200 threads
         * loaded, i.e. ~34ms across a burst of twenty messages.
         */
        this.counterChannels = fields.Many("Thread", {
            inverse: "storeAsCounterChannel",
        });
    },
    computeGlobalCounter() {
        if (!this.Thread) {
            return super.computeGlobalCounter();
        }
        // single pass over Thread.records: this eager compute re-runs on every
        // thread counter mutation (its onUpdate refreshes the app badge)
        const channelsFetched = this.channels.status === "fetched";
        let channelsContribution = channelsFetched ? 0 : this.initChannelsUnreadCounter;
        // Needactions are already counted in the super call, but we want to
        // discard them for channels so there is only +1 per channel.
        let channelsNeedactionCounter = 0;
        // Only channels with something to count: membership already implies the
        // "has unread or needaction" test the contribution used to make, and a
        // channel outside the set adds 0 to the needaction sum by definition.
        for (const thread of this.counterChannels) {
            if (
                channelsFetched &&
                thread.displayToSelf &&
                !thread.self_member_id?.mute_until_dt
            ) {
                channelsContribution++;
            }
            channelsNeedactionCounter += thread.message_needaction_counter;
        }
        return (
            super.computeGlobalCounter() +
            channelsContribution -
            channelsNeedactionCounter
        );
    },
    /** @returns {import("models").Thread[]} */
    getSelfImportantChannels() {
        return this.getSelfRecentChannels().filter(
            (channel) => channel.importantCounter > 0,
        );
    },
    /** @returns {import("models").Thread[]} */
    getSelfRecentChannels() {
        return Object.values(this.Thread.records)
            .filter(
                (thread) => thread.model === "discuss.channel" && thread.self_member_id,
            )
            .sort(
                (a, b) =>
                    compareDatetime(b.lastInterestDt, a.lastInterestDt) || b.id - a.id,
            );
    },
    onStarted() {
        super.onStarted();
        if (this.discuss.isActive) {
            this.channels.fetch();
        }
    },
    onLinkFollowed(fromThread) {
        super.onLinkFollowed(...arguments);
        if (!this.env.isSmall && fromThread?.model === "discuss.channel") {
            fromThread.open({ focus: false });
        }
    },
    /**
     * @override
     * @param {MouseEvent} ev
     * @param {number} id
     */
    onClickPartnerMention(ev, id) {
        this.env.services.popover.add(ev.target, AvatarCardPopover, {
            id,
            model: "res.partner",
        });
    },
};
patch(Store.prototype, StorePatch);
