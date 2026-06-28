// @ts-check
/** @odoo-module native */

/** @module @web/core/lib/chartjs - Lazy ESM loader for Chart.js v4 and its luxon date adapter */

// Chart.js is a real ES module (`static/lib/Chart/Chart.js`, the upstream v4
// auto-registering build) resolved through the `chart.js` import-map entry as
// an external bare specifier, alongside its date adapter
// (`chartjs-adapter-luxon`).  It replaces the old `web.chartjs_lib` bundle of
// classic `<script>`s that assigned `window.Chart`.

/**
 * Live-bound Chart.js constructor.
 *
 * `null` until {@link loadChartJS} has resolved at least once; thereafter
 * every importer observes the loaded constructor through the ES-module live
 * binding, so existing `new Chart(...)` call sites keep working after the
 * load with no further change.
 *
 * @type {any}
 */
export let Chart = null;

/** @type {Promise<any> | null} de-dupes concurrent loads into one fetch. */
let loadPromise = null;

/**
 * Lazily load Chart.js (auto-registering build) and its luxon date adapter,
 * then populate the live-bound {@link Chart} export.
 *
 * Both libs are real ES modules resolved through the import map, so the
 * dynamic `import()` is a single runtime fetch shared across the app — no
 * `<script>` injection, no `window.Chart` global.  The adapter is a
 * side-effect import: evaluating it registers the luxon date adapter onto
 * Chart's shared `_adapters._date`, so time-scale axes format through the same
 * luxon instance the rest of the app uses.
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
        })();
        await loadPromise;
    }
    return Chart;
}
