/** @odoo-module native */
import {
    Component,
    onWillStart,
    onWillUnmount,
    onWillUpdateProps,
    useState,
} from "@odoo/owl";
import { KeepLast } from "@web/core/utils/concurrency";
import { useService } from "@web/core/utils/hooks";
import { debounce } from "@web/core/utils/timing";

import { PurchaseDashboardCard } from "./purchase_dashboard_card.js";

/**
 * One entry per card, in display order. The template iterates this instead of
 * repeating the same markup ten times, which is also what keeps the "my" row
 * from drifting away from the "global" row: both render the same spec with a
 * different `scope`.
 *
 * `filters` is the list of search-view filter *names* the card stands for. Every
 * one of them must exist in the search view — `setSearchContext` throws if not,
 * because a card that silently applies nothing is indistinguishable from a card
 * that legitimately matched no records.
 */
export const PURCHASE_DASHBOARD_CARDS = [
    {
        key: "draft",
        label: "New",
        title: "Draft RFQs",
        filters: ["draft_rfqs"],
        emphasis: "info",
    },
    {
        key: "sent",
        label: "RFQ Sent",
        title: "Sent RFQs",
        filters: ["waiting_rfqs"],
        // Neutral by design: "sent" is a normal resting state, not a signal.
        emphasis: "secondary",
    },
    {
        key: "late",
        label: "Late RFQ",
        title: "Late RFQs",
        filters: ["late"],
        emphasis: "warning",
    },
    { spacer: true },
    {
        key: "not_acknowledged",
        label: "Not Acknowledged",
        title: "Not Acknowledged POs",
        filters: ["not_acknowledged"],
        emphasis: "info",
    },
    {
        key: "late_receipt",
        label: "Late Receipt",
        title: "Late Receipt POs",
        filters: ["late_receipt"],
        emphasis: "danger",
    },
];

export class PurchaseDashBoard extends Component {
    static template = "purchase.PurchaseDashboard";
    static components = { PurchaseDashboardCard };
    static props = {};

    setup() {
        this.orm = useService("orm");
        this.state = useState({ data: null });
        this.cards = PURCHASE_DASHBOARD_CARDS;

        // The debounce collapses a burst of parent re-renders into one RPC; it
        // does not order the responses. KeepLast drops a superseded answer so a
        // slow early request cannot overwrite a fast later one.
        this.keepLast = new KeepLast();

        onWillStart(() => this.updateDashboardState());
        this.debouncedUpdate = debounce(() => this.updateDashboardState(), 250);
        onWillUpdateProps(() => this.debouncedUpdate());
        onWillUnmount(() => this.debouncedUpdate.cancel());
    }

    get purchaseData() {
        return this.state.data;
    }

    /** @returns {boolean} whether other users' orders are in scope */
    get multiuser() {
        return Boolean(this.state.data?.multiuser);
    }

    /**
     * Refresh the aggregate counts.
     *
     * Failures are swallowed on purpose. This component is a strip above the
     * list/kanban renderer, and an unguarded rejection in `onWillStart` escapes
     * as an OwlError: `ControllerComponent.onError` then calls
     * `ActionDispatch.fail()` which, on an initial mount, rejects the action and
     * restores the previous stack — the whole purchase view fails to open rather
     * than opening without its dashboard. Degrade to a hidden strip instead.
     */
    async updateDashboardState() {
        try {
            this.state.data = await this.keepLast.add(
                this.orm.call("purchase.order", "prepare_dashboard"),
            );
        } catch {
            this.state.data = null;
        }
    }

    /**
     * Replace the current search with the filters a card stands for.
     *
     * @param {string[]} filterNames search-view filter names, all of which must exist
     */
    setSearchContext(filterNames) {
        const { searchModel } = this.env;
        const searchItems = searchModel.getSearchItems((item) =>
            filterNames.includes(item.name),
        );
        const found = new Set(searchItems.map((item) => item.name));
        const missing = filterNames.filter((name) => !found.has(name));
        if (missing.length) {
            // Loud on purpose: clearing the query and applying nothing looks
            // exactly like "no records matched", so a renamed or deleted filter
            // used to degrade into a card that quietly did the wrong thing.
            throw new Error(
                `purchase dashboard: no search filter named ${missing.join(", ")}`,
            );
        }
        searchModel.clearQuery();
        for (const item of searchItems) {
            searchModel.toggleSearchItem(item.id);
        }
    }
}
