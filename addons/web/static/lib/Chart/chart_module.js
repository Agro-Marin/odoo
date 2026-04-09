/**
 * Register Chart.js in the legacy module loader.
 *
 * The UMD ``Chart.js`` sets ``globalThis.Chart``.  This shim makes it
 * available via ``require("chart.js")`` for transpiled modules.
 *
 * In production, Chart.js is loaded as ESM via import map — this shim
 * is only needed for non-ESM bundles (e.g. test bundles).
 */
odoo.define("chart.js", [], function () {
    "use strict";
    return Chart;
});
