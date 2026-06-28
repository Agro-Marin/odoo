/** @odoo-module native */

/**
 * @module @spreadsheet/o_spreadsheet/chartjs_setup
 *
 * Installs Chart.js — with its luxon date adapter and spreadsheet's extra
 * geo (choropleth / bubble-map) and treemap plugins — for the generated
 * `o_spreadsheet.js` bundle, which reads `globalThis.Chart` at chart-render
 * time.
 *
 * Chart.js, the adapter and the plugins are all real ES modules resolved
 * through the import map (`chart.js`, `chartjs-adapter-luxon`,
 * `chartjs-chart-geo`, `chartjs-chart-treemap`). This replaces the old
 * `web.chartjs_lib`-plus-classic-plugins bundle that o_spreadsheet relied on
 * via the global:
 *
 *   - The bare `import "chartjs-adapter-luxon"` registers the date adapter
 *     onto the shared Chart (so time-scale axes format through the same luxon
 *     instance as the rest of the app).
 *   - The geo/treemap ESM builds, unlike their old UMD counterparts, do NOT
 *     auto-register, so we register their controllers/elements/scales onto the
 *     shared Chart explicitly below.
 *   - `globalThis.Chart = Chart` then exposes the fully plugged-in constructor
 *     to `o_spreadsheet.js`.
 *
 * This is the single, deliberate Chart global in the codebase: it exists only
 * because `o_spreadsheet.js` is a generated third-party artifact that reads the
 * global rather than importing. All other Chart consumers use the
 * `@web/core/lib/chartjs` loader.
 */

import { Chart } from "chart.js";
import "chartjs-adapter-luxon";
import {
    ChoroplethController,
    BubbleMapController,
    GeoFeature,
    ColorScale,
    ColorLogarithmicScale,
    ProjectionScale,
    SizeScale,
    SizeLogarithmicScale,
} from "chartjs-chart-geo";
import { TreemapController, TreemapElement } from "chartjs-chart-treemap";

Chart.register(
    ChoroplethController,
    BubbleMapController,
    GeoFeature,
    ColorScale,
    ColorLogarithmicScale,
    ProjectionScale,
    SizeScale,
    SizeLogarithmicScale,
    TreemapController,
    TreemapElement,
);

globalThis.Chart = Chart;
