// @ts-check
/** @odoo-module native */

/** @module @web/views/report_search_model - Shared SearchModel factory for report views (graph, pivot) restoring group-bys from saved favorites */

import { SearchModel } from "@web/search/search_model";

// Widen to `any` so dynamically-set instance state (`searchItems`,
// `preparingIrFilterDescription`) and protected methods used by the subclass
// don't trip TS — the strict shape is preserved by the import.
/** @type {any} */
const Base = SearchModel;

/**
 * Build a SearchModel extension for a report view (graph, pivot).
 *
 * Overrides group-by resolution so that favorites saved with `contextKey`
 * in their context restore the correct grouping instead of using the
 * default search-item group-bys.
 *
 * @param {string} contextKey - the favorite context key carrying the
 *   report's group-bys (e.g. `graph_groupbys`, `pivot_row_groupby`)
 * @returns {typeof SearchModel}
 */
export function makeReportSearchModel(contextKey) {
    return class ReportSearchModel extends Base {
        /**
         * Build the ir.filter description, flagging that we are serializing
         * so `_getSearchItemGroupBys` falls back to the default behavior.
         *
         * @returns {Object}
         */
        _getIrFilterDescription() {
            this.preparingIrFilterDescription = true;
            const result = super._getIrFilterDescription(...arguments);
            this.preparingIrFilterDescription = false;
            return result;
        }

        /**
         * Return group-by specs for the given active search item. When a
         * favorite carries `contextKey` in its context, those are used
         * directly (unless we are currently building an ir.filter
         * description).
         *
         * @param {Object} activeItem - the currently active search item
         * @returns {string[]}
         */
        _getSearchItemGroupBys(activeItem) {
            const { searchItemId } = activeItem;
            const { context, type } = this.searchItems[searchItemId];
            if (
                !this.preparingIrFilterDescription &&
                type === "favorite" &&
                context[contextKey]
            ) {
                return context[contextKey];
            }
            return super._getSearchItemGroupBys(...arguments);
        }
    };
}
