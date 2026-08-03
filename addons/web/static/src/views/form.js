// @ts-check
/** @odoo-module native */

/** @module @web/views/form */

/**
 * The form module's published interface.
 *
 * Everything under `views/form/` that another addon imports today is re-exported here,
 * and nothing else. The names below are the contract; the 8 files behind them
 * are not, and may be renamed, split or moved without touching a
 * consumer OUTSIDE `web`. Inside it they are imported directly and a
 * rename does reach them — the face constrains other addons, which is
 * the only direction `js_face_boundary` enforces.
 *
 * Descriptive rather than aspirational: a face invented ahead of demand is a
 * guess. A consumer needing something not listed adds it here — one visible,
 * reviewable edit instead of a reach into a file.
 *
 * A face is a SIBLING file, not `form/index.js`:
 * `ir_qweb_assets._specifier_to_static_url` maps `@web/views/form` to
 * `/web/static/src/views/form.js` by appending `.js`, with no directory-index step.
 */

export { FormArchParser } from "./form/form_arch_parser.js";
export { FormCogMenu } from "./form/form_cog_menu/form_cog_menu.js";
export { FormCompiler, objectToString } from "./form/form_compiler.js";
export { FormController } from "./form/form_controller.js";
export { FormRenderer } from "./form/form_renderer.js";
export { FormStatusIndicator } from "./form/form_status_indicator/form_status_indicator.js";
export { formView } from "./form/form_view.js";
export { Setting } from "./form/setting/setting.js";
