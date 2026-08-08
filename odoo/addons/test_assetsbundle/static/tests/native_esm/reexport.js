/** @odoo-module native */

// `export * from` is the form the bridge generator has to expand transitively
// to know what names the shim must re-export.
export * from "@test_assetsbundle/../tests/native_esm/dep";

export const LOCAL = "local";
