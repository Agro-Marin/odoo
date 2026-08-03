// @ts-check
/** @odoo-module native */

/** @module @web/views/widgets */

/**
 * The widgets module's published interface.
 *
 * Everything under `views/widgets/` that another addon imports today is re-exported here,
 * and nothing else. The names below are the contract; the 4 files behind them
 * are not, and may be renamed, split or moved without touching a
 * consumer OUTSIDE `web`. Inside it they are imported directly and a
 * rename does reach them — the face constrains other addons, which is
 * the only direction `js_face_boundary` enforces.
 *
 * Descriptive rather than aspirational: a face invented ahead of demand is a
 * guess. A consumer needing something not listed adds it here — one visible,
 * reviewable edit instead of a reach into a file.
 *
 * A face is a SIBLING file, not `widgets/index.js`:
 * `ir_qweb_assets._specifier_to_static_url` maps `@web/views/widgets` to
 * `/web/static/src/views/widgets.js` by appending `.js`, with no directory-index step.
 */

export { DocumentationLink } from "./widgets/documentation_link/documentation_link.js";
export { standardWidgetProps } from "./widgets/standard_widget_props.js";
export { WeekDays, weekDays } from "./widgets/week_days/week_days.js";
export { Widget } from "./widgets/widget.js";
