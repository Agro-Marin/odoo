// @ts-check
/** @odoo-module native */

import { makeLazyFacade } from "@web/core/module_bridge";

/** @type {any} */
let _chart = null;

/**
 * @type {any}
 */
export const Chart = makeLazyFacade(() => _chart, { constructable: true });

/** @type {any} */
let _tooltip = null;

/**
 * @type {any}
 */
export const Tooltip = makeLazyFacade(() => _tooltip);

/** @type {Promise<any> | null} */
let loadPromise = null;

/**
 * @returns {Promise<any>}
 */
export async function loadChartJS() {
    if (!_chart) {
        loadPromise ??= (async () => {
            const [chartModule] = await Promise.all([
                import("chart.js"),
                import("chartjs-adapter-luxon"),
            ]);
            _chart = chartModule.Chart;
            _tooltip = chartModule.Tooltip;
            return Chart;
        })().catch((error) => {
            loadPromise = null;
            throw error;
        });
        await loadPromise;
    }
    return Chart;
}
