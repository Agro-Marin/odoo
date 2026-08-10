// @ts-check
/** @odoo-module native */

/** @module @web/views/arch_info */

/**
 * The `archInfo` keys `web` compiles into **generated OWL template source**.
 *
 * `archInfo` is the object an `ArchParser` returns and the view's model,
 * controller, renderer and compiler all read. Most of that traffic is ordinary
 * property access, visible to anyone reading the code. These two are not: the
 * compiler emits them as *text*, into a template it then registers —
 *
 * ```js
 * // views/view_compiler.js
 * `__comp__.props.archInfo.fieldNodes[${toStringExpression(fieldId)}]`
 * ```
 *
 * — so the key exists only inside a string until OWL compiles it. Nothing in
 * this repo can follow it there. `tsc` sees a string; ESLint sees a string; the
 * import, member, layer and surface gates all see a string.
 *
 * Measured, not asserted. Renaming `fieldNodes` in `list_arch_parser.js` alone,
 * leaving every consumer untouched:
 *
 * ```
 * tsc -p tsconfig.json          2106 errors -> 2106 errors   (zero new)
 * pytest tooling/architecture   identical failure set to pristine HEAD
 * hoot @web/views/list/list_view  577 passed -> 509 failed
 * ```
 *
 * A total break of the list view, and every static check in the fork stayed
 * green. `js_arch_info_surface` is what now fails instead.
 *
 * @type {string[]}
 */
export const ARCH_INFO_TEMPLATE_SURFACE = ["fieldNodes", "widgetNodes"];

/**
 * The same, for keys another addon compiles into template source.
 *
 * Recorded rather than owned, as `VIEW_CONFIG_FOREIGN_SURFACE` records the
 * `env.config` squatters: `addons/mail/chatter/web/form_compiler.js` emits
 * `__comp__.props.archInfo.has_activities`, a key mail's own arch parser sets.
 * It is not web's to maintain, but it travels through web's compiler machinery
 * and breaks the same silent way, so the gate must know it is legitimate.
 *
 * @type {string[]}
 */
export const ARCH_INFO_TEMPLATE_FOREIGN_SURFACE = ["has_activities"];

/**
 * The template-scope contract as a type.
 *
 * Deliberately narrow. There is no single `ArchInfo` shape to declare: each
 * view type's parser returns its own, `ListArchParser` closes its return with a
 * spread of attributes read off the arch, and its `@returns` says so with an
 * `[key: string]: any` index signature. A type claiming otherwise would be
 * false for five of the six view types.
 *
 * What *is* uniform is this: whatever else an archInfo carries, these two keys
 * are addressed from compiled template source and may not be renamed without
 * changing the compiler in the same edit.
 *
 * @typedef {{
 *  fieldNodes: Record<string, any>,
 *  widgetNodes: Record<string, any>,
 * }} ArchInfoTemplateScope
 */
