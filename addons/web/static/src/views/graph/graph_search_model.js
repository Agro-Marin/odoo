// @ts-check
/** @odoo-module native */

/** @module @web/views/graph/graph_search_model - SearchModel extension restoring graph_groupbys from saved favorites */

import { makeReportSearchModel } from "@web/views/report_search_model";

/**
 * Search model extension for the graph view.
 *
 * Overrides group-by resolution so that favorites saved with
 * `graph_groupbys` in their context restore the correct grouping
 * instead of using the default search-item group-bys.
 */
export class GraphSearchModel extends makeReportSearchModel("graph_groupbys") {}
