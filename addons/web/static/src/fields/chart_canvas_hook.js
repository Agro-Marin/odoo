// @ts-check
/** @odoo-module native */

import { onWillStart, useRef } from "@odoo/owl";
import { loadChartJS } from "@web/core/lib/chartjs";
import { useLayoutEffect } from "@web/core/utils/layout_effect";

/**
 * @param {() => unknown[]} dependencies
 * @returns {import("@odoo/owl").Ref<HTMLCanvasElement>}
 */
export function useChartCanvas(component, dependencies) {
    const canvasRef = useRef("canvas");
    component.chart = null;

    onWillStart(() => loadChartJS());

    useLayoutEffect(() => {
        component.renderChart();
        return () => {
            if (component.chart) {
                component.chart.destroy();
                component.chart = null;
            }
        };
    }, dependencies);

    return /** @type {any} */ (canvasRef);
}
