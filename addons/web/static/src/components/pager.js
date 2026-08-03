// @ts-check
/** @odoo-module native */

/** @module @web/components/pager */

/**
 * The pager module's published interface.
 *
 * Everything under `components/pager/` that another addon imports today is re-exported
 * here, and nothing else. The name below is the contract; the 2 files behind it
 * are not, and may be renamed, split or moved without touching a
 * consumer OUTSIDE `web`. Inside it they are imported directly and a
 * rename does reach them — the face constrains other addons, which is
 * the only direction `js_face_boundary` enforces.
 *
 * Descriptive rather than aspirational: a face invented ahead of demand is a
 * guess. A consumer needing something not listed adds it here — one visible,
 * reviewable edit instead of a reach into a file.
 *
 * Measured before publishing: 6 consumer files outside `web`, all naming
 * `pager/pager` and all importing exactly `Pager`. `pagerBus`, `PAGER_UPDATED_EVENT`
 * and `PagerIndicator` are reached only from inside `web`, so they are not published —
 * a one-name face is the honest description of the demand, not an oversight.
 *
 * A face is a SIBLING file, not `pager/index.js`:
 * `ir_qweb_assets._specifier_to_static_url` maps `@web/components/pager` to
 * `/web/static/src/components/pager.js` by appending `.js`, with no directory-index step.
 */

export { Pager } from "./pager/pager.js";
