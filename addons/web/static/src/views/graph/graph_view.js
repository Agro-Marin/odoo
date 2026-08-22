// @ts-check
/** @odoo-module native */

import { registry } from "@web/core/registry";
import { _t } from "@web/core/translation";
import { reportViewProps } from "@web/views/view_utils";

import { GraphArchParser } from "./graph_arch_parser.js";
import { GraphController } from "./graph_controller.js";
import { GraphModel } from "./graph_model.js";
import { GraphRenderer } from "./graph_renderer.js";
import { GraphSearchModel } from "./graph_search_model.js";
const viewRegistry = registry.category("views");

export const graphView = {
    type: "graph",
    Controller: GraphController,
    Renderer: GraphRenderer,
    Model: GraphModel,
    ArchParser: GraphArchParser,
    SearchModel: GraphSearchModel,
    buttonTemplate: "web.GraphView.Buttons",

    props: (genericProps, view) =>
        reportViewProps(genericProps, view, {
            fromState: (state) => state.metaData,
            fromArch: (archInfo, { fields, resModel }) => ({
                disableLinking: Boolean(archInfo.disableLinking),
                fieldAttrs: archInfo.fieldAttrs,
                fields,
                groupBy: archInfo.groupBy,
                measure: archInfo.measure || "__count",
                viewMeasures: archInfo.measures,
                mode: archInfo.mode || "bar",
                order: archInfo.order || null,
                resModel,
                stacked: "stacked" in archInfo ? archInfo.stacked : true,
                cumulated: archInfo.cumulated || false,
                cumulatedStart: archInfo.cumulatedStart || false,
                title: archInfo.title || _t("Untitled"),
            }),
        }),
};

viewRegistry.add("graph", graphView);
