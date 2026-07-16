/** @odoo-module native */
import { PortalHomeCounters } from "@portal/interactions/portal_home_counters";
import { patch } from "@web/core/utils/patch";

patch(PortalHomeCounters.prototype, {
    /**
     * @override
     */
    getCountersAlwaysDisplayed() {
        return super.getCountersAlwaysDisplayed(...arguments).concat(["invoice_count"]);
    },
});
