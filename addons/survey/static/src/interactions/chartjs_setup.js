/** @odoo-module native */

/**
 * @module @survey/interactions/chartjs_setup
 *
 * Installs Chart.js (and its luxon date adapter) on `globalThis.Chart` for the
 * survey result/session chart interactions, which build their charts
 * synchronously in `setup()` and therefore expect `Chart` to be present at
 * bundle-evaluation time rather than awaiting a loader.
 *
 * Chart.js and the adapter are real ES modules resolved through the import map
 * (`chart.js`, `chartjs-adapter-luxon`); this replaces the old
 * `('include', 'web.chartjs_lib')` classic-script bundle that assigned the
 * `window.Chart` global. Loaded eagerly with the survey assets, it runs before
 * any survey interaction's `setup()`. (The data-labels plugin used by the live
 * session chart is imported directly by `survey_session_chart.js`.)
 */

import { Chart } from "chart.js";
import "chartjs-adapter-luxon";

globalThis.Chart = Chart;
