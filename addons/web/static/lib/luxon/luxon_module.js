/**
 * Register luxon in the legacy module loader (same pattern as owl/odoo_module.js).
 *
 * The UMD ``luxon.js`` sets ``globalThis.luxon``. This module makes it
 * available to transpiled code via ``require("luxon")``.
 *
 * In production, luxon is loaded as ESM via import map — this shim is
 * only needed for non-ESM bundles (e.g. test bundles).
 */
odoo.define("luxon", [], function () {
    "use strict";
    return luxon;
});
