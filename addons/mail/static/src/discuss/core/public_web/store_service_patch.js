/** @odoo-module native */
import { Store } from "@mail/core/common/store_service";
import { useSequential } from "@mail/utils/common/hooks";
import { rpc } from "@web/core/network/rpc";
import { patch } from "@web/core/utils/patch";
/** @type {import("models").Store} */
const StorePatch = {
    setup() {
        super.setup(...arguments);
        this.channels = this.makeCachedFetchData("channels_as_member");
        this.fetchSearchConversationsSequential = useSequential();
    },
    /** @param {string} searchValue */
    async searchConversations(searchValue) {
        const data = await this.fetchSearchConversationsSequential(() =>
            rpc("/discuss/search", { term: searchValue }),
        );
        // useSequential resolves superseded (out-of-date) calls with undefined;
        // skip the insert so a fast keystroke stream doesn't clobber the store
        // with an empty payload (cf. channel_invitation.js which guards too).
        if (!data) {
            return;
        }
        this.insert(data);
    },
};
patch(Store.prototype, StorePatch);
