// @ts-check
/** @odoo-module native */
import { Thread } from "@mail/core/common/thread_model";
import { makeLogger } from "@web/core/debug/debug_logger";
import { patch } from "@web/core/utils/patch";

const log = makeLogger("mail.thread");
patch(Thread.prototype, {
    /** @param {string[]} requestList */
    async fetchThreadData(requestList) {
        log.pipeline("fetchThreadData", () => ({
            thread: this.localId,
            requestList,
        }));
        if (requestList.includes("messages")) {
            this.fetchNewMessages();
        }
        const endFetch = log.perf("fetchThreadData");
        await this.store.fetchStoreData("mixin.mail.thread", {
            access_params: this.rpcParams,
            request_list: requestList,
            thread_id: this.id,
            thread_model: this.model,
        });
        endFetch({ thread: this.localId, requestList });
    },
});
