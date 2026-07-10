// @ts-check
/** @odoo-module native */

/** @module @web/core/lib/chartjs - Lazy ESM loader for Chart.js v4 and its luxon date adapter */

// Chart.js (`static/lib/Chart/Chart.js`, upstream v4 auto-registering build)
// is resolved as an ES module through the `chart.js` import-map entry,
// replacing the old `web.chartjs_lib` <script> bundle that assigned
// `window.Chart`.

/**
 * Live-bound Chart.js constructor, `null` until {@link loadChartJS} resolves.
 * The ES-module live binding means every importer sees the update in place,
 * so existing `new Chart(...)` call sites keep working with no further change.
 *
 * @type {any}
 */
export let Chart = null;

/** @type {Promise<any> | null} de-dupes concurrent loads into one fetch. */
let loadPromise = null;

/**
 * Lazily load Chart.js and its luxon date adapter, then populate the
 * live-bound {@link Chart} export. The adapter import is side-effect-only:
 * it registers luxon onto Chart's `_adapters._date` so time-scale axes format
 * through the app's shared luxon instance.
 *
 * @returns {Promise<any>} the Chart constructor
 */
export async function loadChartJS() {
    if (!Chart) {
        loadPromise ??= (async () => {
            const [chartModule] = await Promise.all([
                import("chart.js"),
                import("chartjs-adapter-luxon"),
            ]);
            Chart = chartModule.Chart;
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
