// @ts-check
/** @odoo-module native */

/** @module @web/views/pivot/pivot_view */

import { registry } from "@web/core/registry";
import { _t } from "@web/core/translation";
import { PivotArchParser } from "@web/views/pivot/pivot_arch_parser";
import { PivotModel } from "@web/views/pivot/pivot_model";
import { PivotRenderer } from "@web/views/pivot/pivot_renderer";

import { PivotController } from "./pivot_controller.js";
import { PivotSearchModel } from "./pivot_search_model.js";

const viewRegistry = registry.category("views");

export const pivotView = {
    type: "pivot",
    Controller: PivotController,
    Renderer: PivotRenderer,
    Model: PivotModel,
    ArchParser: PivotArchParser,
    SearchModel: PivotSearchModel,
    searchMenuTypes: ["filter", "groupBy", "favorite"],
    buttonTemplate: "web.PivotView.Buttons",

    /**
     * @param {Record<string, any>} genericProps
     * @param {Record<string, any>} view
     * @returns {Record<string, any>}
     */
    props: (genericProps, view) => {
        const modelParams = {};
        if (genericProps.state) {
            modelParams.data = genericProps.state.data;
            modelParams.metaData = genericProps.state.metaData;
        } else {
            const { arch, fields, resModel } = genericProps;

            const archInfo = new view.ArchParser().parse(arch);

            if (!archInfo.activeMeasures.length || archInfo.displayQuantity) {
                archInfo.activeMeasures.unshift("__count");
            }

            modelParams.metaData = {
                activeMeasures: archInfo.activeMeasures,
                colGroupBys: archInfo.colGroupBys,
                defaultOrder: archInfo.defaultOrder,
                disableLinking: Boolean(archInfo.disableLinking),
                fields: fields,
                fieldAttrs: archInfo.fieldAttrs,
                resModel: resModel,
                rowGroupBys: archInfo.rowGroupBys,
                title: archInfo.title || _t("Untitled"),
                widgets: archInfo.widgets,
            };
        }

        return {
            ...genericProps,
            Model: view.Model,
            modelParams,
            Renderer: view.Renderer,
            buttonTemplate: view.buttonTemplate,
        };
    },
};

viewRegistry.add("pivot", pivotView);
