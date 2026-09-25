// @ts-check
/** @odoo-module native */

import { onWillStart, useRef } from "@odoo/owl";
import { useColorScheme } from "@web/core/color_scheme";
import { loadChartJS } from "@web/core/lib/chartjs";
import { useLayoutEffect } from "@web/core/utils/layout_effect";

/**
 * @param {() => unknown[]} dependencies
 * @returns {import("@odoo/owl").Ref<HTMLCanvasElement>}
 */
export function useChartCanvas(component, dependencies) {
    const canvasRef = useRef("canvas");
    const scheme = useColorScheme();
    component.chart = null;

    onWillStart(() => loadChartJS());

    useLayoutEffect(
        () => {
            component.renderChart();
            return () => {
                if (component.chart) {
                    component.chart.destroy();
                    component.chart = null;
                }
            };
        },
        () => [...dependencies(), scheme.current],
    );

    return /** @type {any} */ (canvasRef);
}
