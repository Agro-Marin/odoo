/** @odoo-module native */
import { rpc } from "@web/core/network";
import { registry } from "@web/core/registry";
import { Interaction } from "@web/public/interaction";

export class PortalHomeCounters extends Interaction {
    static selector = ".o_portal_my_home";

    async willStart() {
        return this.updateCounters();
    }

    /**
     * Return a list of counters name linked to a line that we want to keep
     * regardless of the number of documents present
     * @returns {Array}
     */
    getCountersAlwaysDisplayed() {
        return [];
    }

    async updateCounters() {
        const needed = [...this.el.querySelectorAll("[data-placeholder_count]")].map(
            (documentsCounterEl) => documentsCounterEl.dataset["placeholder_count"],
        );
        const numberRpc = Math.min(Math.ceil(needed.length / 5), 3); // max 3 rpc, up to 5 counters by rpc ideally
        const counterByRpc = Math.ceil(needed.length / numberRpc);
        const countersAlwaysDisplayed = this.getCountersAlwaysDisplayed();

        const proms = [...Array(Math.min(numberRpc, needed.length)).keys()].map(
            async (i) => {
                // waitFor: track the RPC against teardown so the .then DOM writes
                // below don't run on a destroyed interaction (detached this.el).
                const documentsCountersData = await this.waitFor(
                    rpc("/my/counters", {
                        counters: needed.slice(
                            i * counterByRpc,
                            (i + 1) * counterByRpc,
                        ),
                    }),
                );
                Object.keys(documentsCountersData).forEach((counterName) => {
                    const documentsCounterEl = this.el.querySelector(
                        `[data-placeholder_count='${counterName}']`,
                    );
                    if (!documentsCounterEl) {
                        // Server returned a counter with no matching placeholder in
                        // this page's DOM; nothing to render for it.
                        return;
                    }
                    documentsCounterEl.textContent = documentsCountersData[counterName];
                    // This value, not the server's initial guess, decides whether the
                    // card is shown. The server renders counter-driven cards hidden,
                    // except when the `portal_counters` session hint says the counter
                    // was non-zero last time — a hint that exists only to avoid a
                    // flash-in and that can be out of date (the documents may since
                    // have been paid, archived or deleted). Re-hiding on a zero is
                    // what keeps such a card from surviving as a permanent link to an
                    // empty page; `getCountersAlwaysDisplayed` is the opt-out for
                    // cards that are meant to stay put at zero.
                    const cardEl = documentsCounterEl.closest(".o_portal_index_card");
                    if (
                        documentsCountersData[counterName] !== 0 ||
                        countersAlwaysDisplayed.includes(counterName)
                    ) {
                        cardEl?.classList.remove("d-none");
                    } else {
                        cardEl?.classList.add("d-none");
                    }
                });
                return documentsCountersData;
            },
        );
        return Promise.all(proms).finally(() => {
            // .finally (not .then): a failed counter RPC must still clear the
            // spinner, otherwise it spins forever and its cards stay hidden.
            // Optional chaining: some portal-home template variants omit the
            // spinner, and a bare .remove() on the null result would throw.
            this.el.querySelector(".o_portal_doc_spinner")?.remove();
        });
    }
}

registry
    .category("public.interactions")
    .add("portal.portal_home_counters", PortalHomeCounters);
