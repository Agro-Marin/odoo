// @ts-check
/** @odoo-module native */

import { makeLazyLib } from "@web/core/lib/lazy_lib";

const chartjs = makeLazyLib(
    async () => {
        const [chartModule] = await Promise.all([
            import("chart.js"),
            import("chartjs-adapter-luxon"),
        ]);
        return chartModule;
    },
    {
        pick: (/** @type {any} */ module) => module.Chart,
        extra: (/** @type {any} */ module) => module.Tooltip,
        constructable: true,
    },
);

/** @type {any} */
export const Chart = chartjs.facade;

/** @type {any} */
export const Tooltip = chartjs.extraFacade;

/**
 * @returns {Promise<any>}
 */
export function loadChartJS() {
    return chartjs.load();
}
