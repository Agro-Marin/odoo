/**
 * Register DOMPurify in the legacy module loader.
 *
 * The UMD ``DOMpurify.js`` sets ``globalThis.DOMPurify``.  This shim
 * makes it available via ``require("dompurify")`` for transpiled modules.
 *
 * In production, DOMPurify is loaded as ESM via import map — this shim
 * is only needed for non-ESM bundles (e.g. test bundles).
 */
odoo.define("dompurify", [], function () {
    "use strict";
    return DOMPurify;
});
