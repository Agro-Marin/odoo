// @ts-check
/** @odoo-module native */

/** @module @web/ui/popover */

/**
 * The popover module's published interface.
 *
 * Everything under `ui/popover/` that another addon imports today is re-exported here,
 * and nothing else. The names below are the contract; the 2 files behind them
 * are not, and may be renamed, split or moved without touching a
 * consumer OUTSIDE `web`. Inside it they are imported directly and a
 * rename does reach them — the face constrains other addons, which is
 * the only direction `js_face_boundary` enforces.
 *
 * Descriptive rather than aspirational: a face invented ahead of demand is a
 * guess. A consumer needing something not listed adds it here — one visible,
 * reviewable edit instead of a reach into a file.
 *
 * A face is a SIBLING file, not `popover/index.js`:
 * `ir_qweb_assets._specifier_to_static_url` maps `@web/ui/popover` to
 * `/web/static/src/ui/popover.js` by appending `.js`, with no directory-index step.
 */

export { Popover } from "./popover/popover.js";
export { makePopover, usePopover } from "./popover/popover_hook.js";

/**
 * Types are part of the contract too. `export { … } from` carries runtime values
 * only, so a typedef reached through this face needs republishing by name — the
 * same "one visible, reviewable edit" the docstring above asks for, applied to
 * the half of the surface that has no runtime binding.
 *
 * @typedef {import("./popover/popover_service.js").PopoverServiceAddOptions} PopoverServiceAddOptions
 * @typedef {import("./popover/popover_hook.js").PopoverHookReturnType} PopoverHookReturnType
 */
