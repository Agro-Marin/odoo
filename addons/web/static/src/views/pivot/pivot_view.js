// @ts-check
/** @odoo-module native */

import { registry } from "@web/core/registry";
import { _t } from "@web/core/translation";
import { PivotArchParser } from "@web/views/pivot/pivot_arch_parser";
import { PivotModel } from "@web/views/pivot/pivot_model";
import { PivotRenderer } from "@web/views/pivot/pivot_renderer";
import { reportViewProps } from "@web/views/view_utils";

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
    buttonTemplate: "web.PivotView.Buttons",

    /**
     * @param {any} genericProps
     * @param {any} view
     */
    props: (genericProps, view) =>
        reportViewProps(genericProps, view, {
            fromState: (state) => ({ data: state.data, metaData: state.metaData }),
            fromArch: (archInfo, { fields, resModel }) => {
                if (!archInfo.activeMeasures.length || archInfo.displayQuantity) {
                    archInfo.activeMeasures.unshift("__count");
                }
                return {
                    metaData: {
                        activeMeasures: archInfo.activeMeasures,
                        colGroupBys: archInfo.colGroupBys,
                        defaultOrder: archInfo.defaultOrder,
                        disableLinking: Boolean(archInfo.disableLinking),
                        fields,
                        fieldAttrs: archInfo.fieldAttrs,
                        resModel,
                        rowGroupBys: archInfo.rowGroupBys,
                        title: archInfo.title || _t("Untitled"),
                        widgets: archInfo.widgets,
                    },
                };
            },
        }),
};

viewRegistry.add("pivot", pivotView);
