/** @odoo-module native */
import {
    Component,
    onWillStart,
    onWillUnmount,
    onWillUpdateProps,
    useState,
} from "@odoo/owl";
import { useService } from "@web/core/utils/hooks";
import { debounce } from "@web/core/utils/timing";

export class PurchaseDashBoard extends Component {
    static template = "purchase.PurchaseDashboard";
    static props = {};
    setup() {
        this.orm = useService("orm");
        this.action = useService("action");
        this.state = useState({ data: null, multiuser: false });

        onWillStart(() => this.updateDashboardState());
        // The parent list/kanban renderer re-renders for many reasons that don't
        // change the aggregate counts (row selection, pager, etc.), and OWL calls
        // onWillUpdateProps on every one of them. Debounce so a burst of renders
        // collapses into a single prepare_dashboard RPC.
        this.debouncedUpdate = debounce(() => this.updateDashboardState(), 250);
        onWillUpdateProps(() => this.debouncedUpdate());
        onWillUnmount(() => this.debouncedUpdate.cancel());
    }

    get purchaseData() {
        return this.state.data;
    }

    get multiuser() {
        return this.state.multiuser;
    }

    async updateDashboardState() {
        const data = await this.orm.call("purchase.order", "prepare_dashboard");
        this.state.data = data;
        this.state.multiuser = data.multiuser;
    }

    /**
     * Clears the current search query and activates the search items named in
     * `filterNames` (the comma-separated `filter_name` from the pressed card).
     */
    setSearchContext(filterNames) {
        const filters = filterNames.split(",");
        const searchItems = this.env.searchModel.getSearchItems((item) =>
            filters.includes(item.name),
        );
        this.env.searchModel.query = [];
        for (const item of searchItems) {
            this.env.searchModel.toggleSearchItem(item.id);
        }
    }
}
