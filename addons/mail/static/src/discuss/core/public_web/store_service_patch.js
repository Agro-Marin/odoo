/** @odoo-module native */
import { Store } from "@mail/core/common/store_service";
import { makeSequential } from "@mail/utils/common/misc";
import { rpc } from "@web/core/network/rpc";
import { patch } from "@web/core/utils/patch";
/** @type {import("models").Store} */
const StorePatch = {
    setup() {
        super.setup(...arguments);
        this.channels = this.makeCachedFetchData("channels_as_member");
        this.fetchSearchConversationsSequential = makeSequential();
    },
    /** @param {string} searchValue */
    async searchConversations(searchValue) {
        const data = await this.fetchSearchConversationsSequential(() =>
            rpc("/discuss/search", { term: searchValue }),
        );
        // useSequential resolves superseded calls with undefined: skip the
        // insert so a keystroke stream can't clobber the store with nothing
        if (!data) {
            return;
        }
        this.insert(data);
    },
};
patch(Store.prototype, StorePatch);
