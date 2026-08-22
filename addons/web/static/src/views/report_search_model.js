// @ts-check
/** @odoo-module native */

import { SearchModel } from "@web/search/search_model";

/** @type {any} */
const Base = SearchModel;

/**
 * @param {string} contextKey
 * @returns {typeof SearchModel}
 */
export function makeReportSearchModel(contextKey) {
    const ReportSearchModel = class extends Base {
        /**
         * @returns {Record<string, any>}
         */
        _getIrFilterDescription() {
            this.preparingIrFilterDescription = true;
            const result = super._getIrFilterDescription(...arguments);
            this.preparingIrFilterDescription = false;
            return result;
        }

        /**
         * @param {Record<string, any>} activeItem
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
    return /** @type {typeof SearchModel} */ (
        /** @type {unknown} */ (ReportSearchModel)
    );
}
