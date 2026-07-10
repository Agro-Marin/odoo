// @ts-check
/** @odoo-module native */

/** @module @web/views/graph/graph_search_model - SearchModel extension restoring graph_groupbys from saved favorites */

import { makeReportSearchModel } from "@web/views/report_search_model";

/**
 * Overrides group-by resolution so favorites saved with `graph_groupbys`
 * restore the correct grouping instead of the default search-item group-bys.
 */
export class GraphSearchModel extends makeReportSearchModel("graph_groupbys") {}
