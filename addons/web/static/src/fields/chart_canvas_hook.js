// @ts-check
/** @odoo-module native */

import { onWillStart, useComponent, useEffect, useRef } from "@odoo/owl";
import { loadChartJS } from "@web/core/lib/chartjs";

/**
 * @param {() => unknown[]} dependencies
 * @returns {import("@odoo/owl").Ref<HTMLCanvasElement>}
 */
export function useChartCanvas(dependencies) {
    const component = /** @type {any} */ (useComponent());
    const canvasRef = useRef("canvas");
    component.chart = null;

    onWillStart(() => loadChartJS());

    useEffect(() => {
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
