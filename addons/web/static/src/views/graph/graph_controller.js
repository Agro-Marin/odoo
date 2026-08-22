// @ts-check
/** @odoo-module native */

import { ReportController } from "@web/views/report_controller";

export class GraphController extends ReportController {
    static template = "web.GraphView";

    /** @returns {Object} */
    getContext() {
        const { measure, groupBy, mode } = this.model.metaData;
        const context = {
            graph_measure: measure,
            graph_mode: mode,
            graph_groupbys: groupBy.map((/** @type {any} */ gb) => gb.spec),
        };
        if (mode !== "pie" && mode !== "scatter") {
            context.graph_order = this.model.metaData.order;
            context.graph_stacked = this.model.metaData.stacked;
            if (mode === "line") {
                context.graph_cumulated = this.model.metaData.cumulated;
            }
        }
        return context;
    }
}
