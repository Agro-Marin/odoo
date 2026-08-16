/** @odoo-module native */
import { fields, Record } from "@mail/core/common/record";
import { threadCompareRegistry } from "@mail/core/common/thread_compare";
import { cleanTerm } from "@mail/utils/common/format";

export class MessagingMenu extends Record {
    threadCandidates = fields.Many("Thread", { inverse: "menuAsThreadCandidate" });

    threads = fields.Many("Thread", {
        /** @this {import("models").MessagingMenu} */
        compute() {
            const store = this.store;
            const searchTerm = cleanTerm(store.discuss?.searchTerm ?? "");
            /** @type {import("models").Thread[]} */
            let threads = this.threadCandidates.filter(
                (thread) =>
                    !searchTerm || cleanTerm(thread.displayName).includes(searchTerm),
            );
            const tab = store.discuss?.activeTab;
            if (tab === "inbox") {
                threads = threads.filter(({ channel_type }) =>
                    this.tabToThreadType("mailbox").includes(channel_type),
                );
            } else if (tab === "starred") {
                threads = store.starred ? [store.starred] : [];
            } else if (tab !== "notification") {
                threads = threads.filter(({ channel_type }) =>
                    this.tabToThreadType(tab).includes(channel_type),
                );
            }
            return threads;
        },
        /**
         * @this {import("models").MessagingMenu}
         * @param {import("models").Thread} thread1
         * @param {import("models").Thread} thread2
         */
        sort(thread1, thread2) {
            const compareFunctions = threadCompareRegistry.getAll();
            for (const fn of compareFunctions) {
                const result = fn(thread1, thread2);
                if (result !== undefined) {
                    return result;
                }
            }
            return thread2.localId > thread1.localId ? 1 : -1;
        },
    });

    /**
     * @param {string} tab
     * @returns {string[]}
     */
    tabToThreadType(tab) {
        return tab === "chat" ? ["chat", "group"] : [tab];
    }
}

MessagingMenu.register();
