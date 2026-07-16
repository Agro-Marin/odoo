/** @odoo-module native */
import { Store } from "@mail/core/common/store_service";
import { AvatarCardPopover } from "@mail/discuss/web/avatar_card/avatar_card_popover";
import { compareDatetime } from "@mail/utils/common/misc";
import { patch } from "@web/core/utils/patch";
/** @type {import("models").Store} */
const StorePatch = {
    setup() {
        super.setup(...arguments);
        this.initChannelsUnreadCounter = 0;
    },
    computeGlobalCounter() {
        if (!this.Thread) {
            return super.computeGlobalCounter();
        }
        // single pass over Thread.records: this is an eager compute whose
        // onUpdate refreshes the app badge, so it re-runs on every thread
        // counter mutation — two separate full scans doubled that cost.
        const channelsFetched = this.channels.status === "fetched";
        let channelsContribution = channelsFetched ? 0 : this.initChannelsUnreadCounter;
        // Needactions are already counted in the super call, but we want to
        // discard them for channels so there is only +1 per channel.
        let channelsNeedactionCounter = 0;
        for (const thread of Object.values(this.Thread.records)) {
            if (
                channelsFetched &&
                thread.displayToSelf &&
                !thread.self_member_id?.mute_until_dt &&
                (thread.self_member_id?.message_unread_counter ||
                    thread.message_needaction_counter)
            ) {
                channelsContribution++;
            }
            if (thread.model === "discuss.channel") {
                channelsNeedactionCounter += thread.message_needaction_counter;
            }
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
