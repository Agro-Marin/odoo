// @ts-check
/** @odoo-module native */

/** @module @web/views/pivot/pivot_search_model - SearchModel extension restoring pivot_row_groupby from saved favorites */

import { makeReportSearchModel } from "@web/views/report_search_model";

/**
 * Overrides group-by resolution so favorites saved with `pivot_row_groupby`
 * restore the correct row grouping instead of the default search-item group-bys.
 */
export class PivotSearchModel extends makeReportSearchModel("pivot_row_groupby") {}
