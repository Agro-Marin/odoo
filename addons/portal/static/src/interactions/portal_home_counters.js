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
     * @returns {Array}
     */
    getCountersAlwaysDisplayed() {
        return [];
    }

    async updateCounters() {
        const needed = [...this.el.querySelectorAll("[data-placeholder_count]")].map(
            (documentsCounterEl) => documentsCounterEl.dataset["placeholder_count"],
        );
        const numberRpc = Math.min(Math.ceil(needed.length / 5), 3);
        const counterByRpc = Math.ceil(needed.length / numberRpc);
        const countersAlwaysDisplayed = this.getCountersAlwaysDisplayed();

        const proms = [...Array(Math.min(numberRpc, needed.length)).keys()].map(
            async (i) => {
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
                        return;
                    }
                    documentsCounterEl.textContent = documentsCountersData[counterName];
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
            this.el.querySelector(".o_portal_doc_spinner")?.remove();
        });
    }
}

registry
    .category("public.interactions")
    .add("portal.portal_home_counters", PortalHomeCounters);
