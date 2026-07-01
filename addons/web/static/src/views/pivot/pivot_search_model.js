// @ts-check
/** @odoo-module native */

/** @module @web/views/pivot/pivot_search_model - SearchModel extension restoring pivot_row_groupby from saved favorites */

import { makeReportSearchModel } from "@web/views/report_search_model";

/**
 * Search model extension for the pivot view.
 *
 * Overrides group-by resolution so that favorites saved with
 * `pivot_row_groupby` in their context restore the correct row
 * grouping instead of using the default search-item group-bys.
 */
export class PivotSearchModel extends makeReportSearchModel("pivot_row_groupby") {}
