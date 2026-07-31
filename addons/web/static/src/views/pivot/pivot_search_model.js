// @ts-check
/** @odoo-module native */

/** @module @web/views/pivot/pivot_search_model */

import { makeReportSearchModel } from "@web/views/report_search_model";

export class PivotSearchModel extends makeReportSearchModel("pivot_row_groupby") {}
