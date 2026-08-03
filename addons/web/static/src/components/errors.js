// @ts-check
/** @odoo-module native */

/** @module @web/components/errors */

/**
 * The errors module's published interface.
 *
 * Everything under `components/errors/` that another addon imports today is re-exported
 * here, and nothing else. The names below are the contract; the 2 files behind them
 * are not, and may be renamed, split or moved without touching a
 * consumer OUTSIDE `web`. Inside it they are imported directly and a
 * rename does reach them — the face constrains other addons, which is
 * the only direction `js_face_boundary` enforces.
 *
 * Descriptive rather than aspirational: a face invented ahead of demand is a
 * guess. A consumer needing something not listed adds it here — one visible,
 * reviewable edit instead of a reach into a file.
 *
 * Measured before publishing: 13 consumer files outside `web`, all naming
 * `errors/error_dialogs` and between them these four names. `error_handlers.js` has
 * **no** external consumer, so it stays behind the face rather than being published
 * on the assumption that someone will want it.
 *
 * A face is a SIBLING file, not `errors/index.js`:
 * `ir_qweb_assets._specifier_to_static_url` maps `@web/components/errors` to
 * `/web/static/src/components/errors.js` by appending `.js`, with no directory-index step.
 */

export {
    ErrorDialog,
    odooExceptionTitleMap,
    RPCErrorDialog,
    WarningDialog,
} from "./errors/error_dialogs.js";
