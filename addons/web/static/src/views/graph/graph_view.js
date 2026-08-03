// @ts-check
/** @odoo-module native */

/** @module @web/views/graph/graph_view */

import { registry } from "@web/core/registry";
import { _t } from "@web/core/translation";

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
    searchMenuTypes: ["filter", "groupBy", "favorite"],
    buttonTemplate: "web.GraphView.Buttons",

    /**
     * @param {Record<string, any>} genericProps
     * @param {Record<string, any>} view
     * @returns {Record<string, any>}
     */
    props: (genericProps, view) => {
        let modelParams;
        if (genericProps.state) {
            modelParams = genericProps.state.metaData;
        } else {
            const { arch, fields, resModel } = genericProps;
            const parser = new view.ArchParser();
            const archInfo = parser.parse(arch, fields);
            modelParams = {
                disableLinking: Boolean(archInfo.disableLinking),
                fieldAttrs: archInfo.fieldAttrs,
                fields: fields,
                groupBy: archInfo.groupBy,
                measure: archInfo.measure || "__count",
                viewMeasures: archInfo.measures,
                mode: archInfo.mode || "bar",
                order: archInfo.order || null,
                resModel: resModel,
                stacked: "stacked" in archInfo ? archInfo.stacked : true,
                cumulated: archInfo.cumulated || false,
                cumulatedStart: archInfo.cumulatedStart || false,
                title: archInfo.title || _t("Untitled"),
            };
        }

        return {
            ...genericProps,
            modelParams,
            Model: view.Model,
            Renderer: view.Renderer,
            buttonTemplate: view.buttonTemplate,
        };
    },
};

viewRegistry.add("graph", graphView);
