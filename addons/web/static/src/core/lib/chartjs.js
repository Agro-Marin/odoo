// @ts-check
/** @odoo-module native */

/** @module @web/core/lib/chartjs - Lazy ESM loader for Chart.js v4 and its luxon date adapter */

import { makeLazyFacade } from "@web/core/module_bridge";

// Chart.js (`static/lib/Chart/Chart.js`, upstream v4 auto-registering build)
// is resolved as an ES module through the `chart.js` import-map entry,
// replacing the old `web.chartjs_lib` <script> bundle that assigned
// `window.Chart`.

/** @type {any} the loaded Chart constructor, null until {@link loadChartJS} resolves */
let _chart = null;

/**
 * Stable facade over the lazily-loaded Chart.js constructor: property reads
 * and `new Chart(...)` forward to the loaded constructor, so existing call
 * sites keep working with no further change — including through module
 * bridges (iframe bundles), which snapshot exported values and would never
 * see a mutable `export let` reassignment (see the bridge contract in
 * `@web/core/module_bridge`). Callers must still `await loadChartJS()`
 * before use.
 *
 * @type {any}
 */
export const Chart = makeLazyFacade(() => _chart, { constructable: true });

/** @type {any} the loaded Tooltip plugin, null until {@link loadChartJS} resolves */
let _tooltip = null;

/**
 * The Tooltip plugin, as a facade matching {@link Chart}.
 *
 * Chart.js v3 hung this off the constructor as `Chart.Tooltip`; v4 removed
 * that static and exports `Tooltip` as a separate named export, so call sites
 * carried over from v3 read `undefined` and threw on the first property
 * access (e.g. `Chart.Tooltip.positioners`). Importing `chart.js` directly to
 * get it would defeat the lazy loading this module exists for, so expose it
 * here instead. Callers must `await loadChartJS()` first, exactly as for
 * {@link Chart}.
 *
 * @type {any}
 */
export const Tooltip = makeLazyFacade(() => _tooltip);

/** @type {Promise<any> | null} de-dupes concurrent loads into one fetch. */
let loadPromise = null;

/**
 * Lazily load Chart.js and its luxon date adapter, then populate the
 * {@link Chart} facade. The adapter import is side-effect-only: it
 * registers luxon onto Chart's `_adapters._date` so time-scale axes format
 * through the app's shared luxon instance.
 *
 * @returns {Promise<any>} the Chart constructor (facade)
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
            // Never cache a rejection: a transient fetch failure would
            // otherwise disable every future chart until a full page
            // reload (the pre-ESM loadJS path also allowed retries).
            loadPromise = null;
            throw error;
        });
        await loadPromise;
    }
    return Chart;
}
