/** @odoo-module native */
import { fields, Record } from "@mail/core/common/record";
import { threadCompareRegistry } from "@mail/core/common/thread_compare";
import { cleanTerm } from "@mail/utils/common/format";

/**
 * What the systray messaging menu shows: the candidate threads, the subset the
 * active tab and search leave, and the tab-to-channel-type mapping between them.
 *
 * This is a view-model, and it lived on `Store` — the record registry, the
 * batched RPC client and the session identity — because `menuThreadCandidates`
 * needs a relational field with an inverse, and a relation has to live on a
 * record. It does; it just does not have to live on *that* record. A singleton
 * record of its own is the shape `ChatHub` already uses for exactly this
 * (`store.chatHub = fields.One("ChatHub", { compute: () => ({}) })`), so the
 * menu's derived state is reachable as `store.messagingMenu` and is no longer
 * part of the store's own surface.
 *
 * Layer: `core/common`, not `core/public_web` where the component lives. The
 * inverse is declared on `Thread` (`menuAsThreadCandidate`), which is
 * common-layer, and `makeStore` resolves `fields.One("MessagingMenu")` by name —
 * so a model absent from the bundle is a startup crash, not a missing feature.
 * Sharing a name with the component is the convention here, not an oversight:
 * `ChatWindow` and `ChatHub` are each a Record and a Component too.
 */
export class MessagingMenu extends Record {
    /**
     * Threads eligible for the messaging menu at all, before this menu's own
     * search and tab filtering. Maintained by each thread
     * (@see Thread.menuAsThreadCandidate) rather than rescanned here.
     *
     * Reading `Thread.records` instead made `threads` an observer of the record
     * keys plus `displayToSelf` and `needactionMessages` on *every* thread in
     * the store, so each thread inserted re-ran the whole O(n) scan: measured at
     * ~1.3ms per recompute with 200 threads loaded, i.e. ~13ms to insert ten of
     * them.
     */
    threadCandidates = fields.Many("Thread", { inverse: "menuAsThreadCandidate" });

    threads = fields.Many("Thread", {
        /** @this {import("models").MessagingMenu} */
        compute() {
            const store = this.store;
            // `discuss` and `starred` only exist once the web/public_web
            // patches are applied: guard so portal/livechat bundles that load
            // core/common alone don't crash.
            const searchTerm = cleanTerm(store.discuss?.searchTerm ?? "");
            // Iterate the maintained candidate list, NOT Thread.records: the
            // latter re-observes every thread in the store (see
            // threadCandidates) and, because eligibility now lives in
            // Thread.menuAsThreadCandidate rather than here, would also let
            // ineligible threads into the menu.
            /** @type {import("models").Thread[]} */
            let threads = this.threadCandidates.filter(
                // Skip the per-thread cleanTerm(displayName) normalization when
                // no search is active (the common case): includes("") is always
                // true, so it only ever cost CPU on every recompute.
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
     * The channel types a menu tab shows. `im_livechat` extends this.
     *
     * @param {string} tab
     * @returns {string[]}
     */
    tabToThreadType(tab) {
        return tab === "chat" ? ["chat", "group"] : [tab];
    }
}

MessagingMenu.register();
