// @ts-check
/** @odoo-module native */

/** @module @web/views/view_components */

/**
 * The shared view sub-components' published interface.
 *
 * Everything under `views/view_components/` that another addon imports today is
 * re-exported here, and nothing else. The names below are the contract; the 7
 * files behind them are not, and may be renamed, split or moved without
 * touching a consumer OUTSIDE `web`. Inside it they are imported directly and a
 * rename does reach them — the face constrains other addons, which is the only
 * direction `js_face_boundary` enforces.
 *
 * Descriptive rather than aspirational: a face invented ahead of demand is a
 * guess. This one is not a guess — **12 files across `odoo`, `enterprise` and
 * the sibling repos reached into this directory for 6 distinct modules**
 * (`hr_work_entry`, `base_automation`, `documents`, `project`,
 * `web_enterprise`, `web_gantt` ×2, `mrp_mps`, `web_grid`, `web_cohort`,
 * `helpdesk`), several of them to *patch* what they found. A consumer needing
 * something not listed adds it here — one visible, reviewable edit instead of a
 * reach into a file.
 *
 * The sibling `views/settings/` was considered at the same time and
 * deliberately left unfaced: one external consumer naming one module, where a
 * face publishes nothing the specifier does not already say.
 *
 * A face is a SIBLING file, not `view_components/index.js`:
 * `ir_qweb_assets._specifier_to_static_url` maps `@web/views/view_components`
 * to `/web/static/src/views/view_components.js` by appending `.js`, and
 * performs no directory-index resolution.
 */

export { GroupConfigMenu } from "./view_components/group_config_menu.js";
export { MultiCreatePopover } from "./view_components/multi_create_popover.js";
export { MultiSelectionButtons } from "./view_components/multi_selection_buttons.js";
export { ReportViewMeasures } from "./view_components/report_view_measures.js";
export { SelectionBox } from "./view_components/selection_box.js";
export { ViewScaleSelector } from "./view_components/view_scale_selector.js";
