/** @odoo-module native */
import { registry } from "@web/core/registry";
import { graphView } from "@web/views/graph";

import { BurndownChartModel } from "./burndown_chart_model.js";
import { BurndownChartSearchModel } from "./burndown_chart_search_model.js";

const viewRegistry = registry.category("views");

const burndownChartGraphView = {
    ...graphView,
    buttonTemplate: "project.BurndownChartView.Buttons",
    hideCustomGroupBy: true,
    Model: BurndownChartModel,
    SearchModel: BurndownChartSearchModel,
};

viewRegistry.add("burndown_chart", burndownChartGraphView);
