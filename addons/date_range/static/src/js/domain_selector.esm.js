/** @odoo-module native */

import { onWillStart } from "@odoo/owl";
import { DomainSelector } from "@web/components/domain_selector/domain_selector";
import { patch } from "@web/core/utils/patch";
import { useService } from "@web/core/utils/hooks";
import { _t } from "@web/core/translation";
import { setDateRanges } from "./date_range_provider.js";

/**
 * Prime the period provider before the editor renders.
 *
 * This is the module's only patch of the domain editor. The periods themselves
 * are contributed through `@web/core/tree`, whose contract is
 * synchronous — so something has to have fetched them by the time the value
 * editor is built, and the component that owns the editor is the only place
 * that knows when that is. `date_range_service` caches, so the round trip
 * happens once per session however many selectors are opened.
 */
patch(DomainSelector.prototype, {
    setup() {
        super.setup(...arguments);
        this.dateRangeService = useService("date_range");
        this.notification = useService("notification");

        onWillStart(async () => {
            try {
                const { ranges } = await this.dateRangeService.loadDateRanges();
                setDateRanges(ranges);
            } catch {
                // The domain editor stays usable without periods: the provider
                // simply offers none, and the built-in value types are still
                // there. A console.error alongside this was both duplicate and
                // an eslint no-undef error, `console` not being a declared
                // global.
                setDateRanges([]);
                this.notification.add(
                    _t(
                        "Date ranges could not be loaded. Date range filters will not be available.",
                    ),
                    { type: "warning", sticky: false },
                );
            }
        });
    },
});
