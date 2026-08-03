// @ts-check
/** @odoo-module native */

/** @module @web/components/dropdown */

/**
 * The dropdown module's published interface.
 *
 * Everything under `components/dropdown/` that another addon imports today is re-exported here,
 * and nothing else. The names below are the contract; the 5 files behind them
 * are not, and may be renamed, split or moved without touching a
 * consumer OUTSIDE `web`. Inside it they are imported directly and a
 * rename does reach them — the face constrains other addons, which is
 * the only direction `js_face_boundary` enforces.
 *
 * Descriptive rather than aspirational: a face invented ahead of demand is a
 * guess. A consumer needing something not listed adds it here — one visible,
 * reviewable edit instead of a reach into a file.
 *
 * A face is a SIBLING file, not `dropdown/index.js`:
 * `ir_qweb_assets._specifier_to_static_url` maps `@web/components/dropdown` to
 * `/web/static/src/components/dropdown.js` by appending `.js`, with no directory-index step.
 */

export { AccordionItem } from "./dropdown/accordion_item.js";
export { CheckboxItem } from "./dropdown/checkbox_item.js";
export { Dropdown, getFirstElementOfNode } from "./dropdown/dropdown.js";
export {
    DropdownState,
    useDropdownCloser,
    useDropdownState,
} from "./dropdown/dropdown_hooks.js";
export { DropdownItem } from "./dropdown/dropdown_item.js";
