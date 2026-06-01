// @ts-check
/** @odoo-module native */

/** @module @web/core/l10n/luxon - Typed re-exports of the Luxon DateTime library exposed on globalThis by the vendored UMD bundle */

// Luxon is vendored as a classic IIFE (`static/lib/luxon/luxon.js`) that
// installs `globalThis.luxon` BEFORE the ESM bundle evaluates — verified by
// its placement at the top of `web._assets_core` and `web.assets_frontend`
// in `__manifest__.py`. ESM modules historically accessed Luxon via the
// `/** @type {any} */ (globalThis).luxon` cast at module top level. This
// shim consolidates that cast into a single typed surface so consumers
// import named symbols directly:
//
//   import { DateTime } from "@web/core/l10n/luxon";
//
// instead of repeating the JSDoc cast in every consumer. Eliminates ~46 of
// the 49 occurrences of the cast pattern; preserves runtime behavior
// exactly (every export is a live reference to the same constructor the
// pre-shim consumers received).
//
// DO NOT import this from `static/src/legacy/js/public/public_root.js`:
// the legacy public bundle (`assets_frontend_minimal`) does not include
// Luxon, so that file accesses `globalThis.luxon` lazily inside a closure.
// Eager module-load import would crash the legacy bundle.

/** @import * as LuxonTypes from "luxon" */

const _luxon = /** @type {typeof LuxonTypes} */ (
    /** @type {any} */ (globalThis).luxon ?? {}
);

export const DateTime = _luxon.DateTime;
export const Duration = _luxon.Duration;
export const Interval = _luxon.Interval;
export const Settings = _luxon.Settings;
export const Info = _luxon.Info;
export const Zone = _luxon.Zone;
export const FixedOffsetZone = _luxon.FixedOffsetZone;
export const IANAZone = _luxon.IANAZone;
export const InvalidZone = _luxon.InvalidZone;
export const SystemZone = _luxon.SystemZone;
export const VERSION = _luxon.VERSION;

// Namespace re-export for the rare consumer (e.g. kanban_record.js sandbox
// context) that passes the entire Luxon object as a single value.
export const luxon = _luxon;
