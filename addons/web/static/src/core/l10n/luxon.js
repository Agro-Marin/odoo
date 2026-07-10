// @ts-check
/** @odoo-module native */

/** @module @web/core/l10n/luxon - Typed re-exports of the Luxon DateTime library (real ESM build, resolved via the import map) */

// Luxon ships as a real ES module at `static/lib/luxon/luxon.js` (the upstream
// 3.7.2 ESM build plus the fork's `Symbol.toStringTag` patch for the OWL
// reactivity system), resolved through the `luxon` import-map entry as an
// external bare specifier — one shared instance across every bundle.
//
// This module is the fork's stable, typed re-export surface so consumers keep
// importing named symbols from a `@web/...` path:
//
//   import { DateTime } from "@web/core/l10n/luxon";
//
// rather than the bare `luxon` specifier directly.  Both resolve to the same
// instance; this indirection survives (now as a plain re-export) from the era
// when luxon was a `globalThis.luxon` global laundered through a shim that
// cast it to the typed surface.  The old "do not import from public_root.js"
// caveat is gone: luxon is in the import map for every ESM bundle (frontend
// minimal included), so eager top-level imports resolve through the module
// graph instead of racing a global that "may not be available yet".

export {
    DateTime,
    Duration,
    FixedOffsetZone,
    IANAZone,
    Info,
    Interval,
    InvalidZone,
    Settings,
    SystemZone,
    VERSION,
    Zone,
} from "luxon";

// Namespace re-export for the rare consumer (e.g. kanban_record sandbox
// context) that passes the entire Luxon object as a single value.
export { default as luxon } from "luxon";
