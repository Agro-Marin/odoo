// @ts-check
/** @odoo-module native */

/** @module @web/fields/relational/many2many_tags */

/**
 * The many2many tags module's published interface.
 *
 * Everything under `fields/relational/many2many_tags/` that another addon imports today is re-exported here,
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
 * A face is a SIBLING file, not `many2many_tags/index.js`:
 * `ir_qweb_assets._specifier_to_static_url` maps `@web/fields/relational/many2many_tags` to
 * `/web/static/src/fields/relational/many2many_tags.js` by appending `.js`, with no directory-index step.
 */

export { KanbanMany2ManyTagsField } from "./many2many_tags/kanban_many2many_tags_field.js";
export {
    Many2ManyTagsField,
    many2ManyTagsField,
    Many2ManyTagsFieldColorEditable,
    many2ManyTagsFieldColorEditable,
} from "./many2many_tags/many2many_tags_field.js";
