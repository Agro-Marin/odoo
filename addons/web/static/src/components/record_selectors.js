// @ts-check
/** @odoo-module native */

/** @module @web/components/record_selectors */

/**
 * The record selectors module's published interface.
 *
 * Everything under `components/record_selectors/` that another addon imports today is re-exported here,
 * and nothing else. The names below are the contract; the 3 files behind them
 * are not, and may be renamed, split or moved without touching a
 * consumer OUTSIDE `web`. Inside it they are imported directly and a
 * rename does reach them — the face constrains other addons, which is
 * the only direction `js_face_boundary` enforces.
 *
 * Descriptive rather than aspirational: a face invented ahead of demand is a
 * guess. A consumer needing something not listed adds it here — one visible,
 * reviewable edit instead of a reach into a file.
 *
 * A face is a SIBLING file, not `record_selectors/index.js`:
 * `ir_qweb_assets._specifier_to_static_url` maps `@web/components/record_selectors` to
 * `/web/static/src/components/record_selectors.js` by appending `.js`, with no directory-index step.
 */

export { MultiRecordSelector } from "./record_selectors/multi_record_selector.js";
export { RecordSelector } from "./record_selectors/record_selector.js";
export { useTagNavigation } from "./record_selectors/tag_navigation_hook.js";
