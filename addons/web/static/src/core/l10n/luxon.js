// @ts-check
/** @odoo-module native */

/** @module @web/core/l10n/luxon - Typed re-exports of the Luxon DateTime library (real ESM build, resolved via the import map) */

// Luxon ships as a real ES module (upstream 3.7.2 build plus the fork's
// `Symbol.toStringTag` patch for OWL reactivity), resolved via the `luxon`
// import-map entry — one shared instance across every bundle. This module is
// the fork's stable, typed re-export surface so consumers import named
// symbols from `@web/...` (e.g. `import { DateTime } from "@web/core/l10n/luxon"`)
// instead of the bare `luxon` specifier.

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
