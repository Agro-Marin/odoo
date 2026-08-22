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

        this.keepLast = new KeepLast();

        onWillStart(() => this.updateDashboardState());
        this.debouncedUpdate = debounce(() => this.updateDashboardState(), 250);
        onWillUpdateProps(() => this.debouncedUpdate());
        onWillUnmount(() => this.debouncedUpdate.cancel());
    }

    get purchaseData() {
        return this.state.data;
    }

    /** @returns {boolean} */
    get multiuser() {
        return Boolean(this.state.data?.multiuser);
    }

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
     * @param {string[]} filterNames
     */
    setSearchContext(filterNames) {
        const { searchModel } = this.env;
        const searchItems = searchModel.getSearchItems((item) =>
            filterNames.includes(item.name),
        );
        const found = new Set(searchItems.map((item) => item.name));
        const missing = filterNames.filter((name) => !found.has(name));
        if (missing.length) {
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
