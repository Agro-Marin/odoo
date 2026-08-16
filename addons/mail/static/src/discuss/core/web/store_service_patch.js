/** @odoo-module native */
import { fields } from "@mail/core/common/record";
import { Store } from "@mail/core/common/store_service";
import { compareDatetime } from "@mail/utils/common/misc";
import { patch } from "@web/core/utils/patch";
/**
 * @type {Partial<import("models").Store> & ThisType<import("models").Store>}
 */
const StorePatch = {
    setup() {
        super.setup(...arguments);
        this.initChannelsUnreadCounter = 0;
        this.counterChannels = fields.Many("Thread", {
            inverse: "storeAsCounterChannel",
        });
    },
    computeGlobalCounter() {
        if (!this.Thread) {
            return super.computeGlobalCounter();
        }
        const channelsFetched = this.channels.status === "fetched";
        let channelsContribution = channelsFetched ? 0 : this.initChannelsUnreadCounter;
        let channelsNeedactionCounter = 0;
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
};
patch(Store.prototype, StorePatch);
