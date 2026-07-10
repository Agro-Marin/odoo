// @ts-check
/** @odoo-module native */

/** @module @web/fields/_registry - Central registration helper for field widgets, with optional typed-spec overload */

import { registry } from "@web/core/registry";

/**
 * Top-level view prefixes used by view-specific widget variants: the five
 * canonical view types, plus the settings-form pseudo-view
 * ``base_settings`` (passed as ``viewType`` by the settings arch parser).
 *
 * Constrains the typed-API ``view`` field so typos are caught at
 * IDE/tsc-noEmit time. A new view prefix should widen this union or fall
 * back to the legacy string form (``registerField("myview.mywidget", ...)``).
 *
 * @typedef {"list" | "form" | "kanban" | "calendar" | "hierarchy" | "base_settings"} FieldViewPrefix
 */

/**
 * Typed spec for a field-widget registration. Use this object form instead
 * of a pre-composed string when a widget registers under a view-prefixed
 * key — typos in ``view`` become a compile-time error via the
 * {@link FieldViewPrefix} union.
 *
 * - ``name`` is the widget identifier the view arch references via
 *   ``widget="<name>"`` — NOT necessarily the field type (e.g.
 *   ``res_partner_many2one`` is a widget name, not a type; see
 *   ``getFieldFromRegistry`` for the widget-vs-type fallback).
 * - ``view`` is the optional view prefix; omitting it registers the
 *   default (view-agnostic) variant.
 * - ``aliases`` maps additional keys to the SAME widget object as the
 *   primary registration (string or nested {@link FieldRegistrationSpec},
 *   e.g. ``{ name: "one2many", view: "calendar" }``).
 *   Use only when every key targets the same widget instance — a
 *   view-variant widget with different behaviour (e.g.
 *   ``many2ManyTagsField`` vs. ``many2ManyTagsFieldColorEditable``) needs
 *   its own {@link registerField} call, or it would silently bind to the
 *   base widget. Aliases form a flat set: nested ``aliases`` on an alias
 *   entry are ignored.
 *
 * @typedef {{
 *   name: string;
 *   view?: FieldViewPrefix;
 *   aliases?: Array<string | { name: string; view?: FieldViewPrefix }>;
 * }} FieldRegistrationSpec
 */

/**
 * Compose the registry key for a field registration. Pure string
 * builder — useful when callers need the composed key (debug surfaces,
 * the legacy ``registry.category("fields").add(...)`` pattern in test
 * fixtures). Production code should prefer the
 * {@link registerField} object overload, which calls this internally.
 *
 *   fieldKey({ name: "text", view: "list" }) === "list.text"
 *   fieldKey({ name: "many2one" })           === "many2one"
 *
 * @param {FieldRegistrationSpec} spec
 * @returns {string}
 */
export function fieldKey(spec) {
    return spec.view ? `${spec.view}.${spec.name}` : spec.name;
}

/**
 * Register a field widget into the live ``fields`` registry.
 *
 * Two call shapes are accepted, both forwarding to the same underlying
 * ``registry.category("fields").add(...)``:
 *
 * 1. **Legacy string form** — backward-compatible:
 *
 *    ```js
 *    registerField("text", widget);          // plain
 *    registerField("list.text", widget);     // view-prefixed
 *    ```
 *
 * 2. **Typed spec form** — preferred for view-prefixed widgets so
 *    typos in the view slug become a compile-time error:
 *
 *    ```js
 *    registerField({ name: "text", view: "list" }, widget);
 *    ```
 *
 * 3. **Spec with aliases** — fold multiple same-widget registrations
 *    into a single call. Each ``aliases`` entry becomes an additional
 *    registry key pointing at the SAME widget object:
 *
 *    ```js
 *    registerField(
 *        { name: "one2many", aliases: ["many2many"] },
 *        x2ManyField,
 *    );
 *    registerField({
 *        name: "many2many_tags",
 *        aliases: [
 *            { name: "one2many", view: "calendar" },
 *            { name: "many2many", view: "calendar" },
 *        ],
 *    }, many2ManyTagsField);
 *    ```
 *
 *    Aliases are limited to the same-widget case; a variant widget
 *    (different component/``extractProps``) must use its own call so the
 *    registration site reads as a deliberate new variant.
 *
 * Returns the widget so call sites stay one-liners and downstream
 * addons can chain (``const w = registerField(spec, widget);``).
 *
 * Historical note: a parallel ``FIELD_WIDGETS`` Map + drift-detector test
 * once shadowed the registry for tooling that never materialized; removed
 * as dead scaffolding. Reintroduce only alongside a real consumer.
 *
 * @template T
 * @param {string | FieldRegistrationSpec} nameOrSpec - Registry key
 *   (legacy string form, e.g. ``"char"``, ``"list.text"``,
 *   ``"kanban.progressbar"``) or a typed spec.
 * @param {T} widget - Widget descriptor with component, displayName,
 *   supportedTypes, …
 * @param {...any} rest - Forwarded opaquely to ``registry.add`` (e.g.
 *   ``force`` flag, sequence number).
 * @returns {T}
 */
export function registerField(nameOrSpec, widget, ...rest) {
    const fieldsReg = registry.category("fields");
    const primaryKey =
        typeof nameOrSpec === "string" ? nameOrSpec : fieldKey(nameOrSpec);
    // ``widget`` is the caller's generic ``T``; the fields registry shape is
    // declared in ``@types/registries/registries.d.ts``. Cast at the boundary
    // so callers retain their precise ``T`` return type.
    fieldsReg.add(primaryKey, /** @type {any} */ (widget), ...rest);
    if (typeof nameOrSpec !== "string" && nameOrSpec.aliases?.length) {
        // Bind every alias to the SAME ``widget`` reference so subsequent
        // ``fieldRegistry.get(<alias>)`` returns the canonical object. The
        // forwarded ``rest`` arguments (``force``, ``sequence``) apply
        // identically to each alias so they share lookup ordering with the
        // primary key.
        for (const alias of nameOrSpec.aliases) {
            const aliasKey = typeof alias === "string" ? alias : fieldKey(alias);
            fieldsReg.add(aliasKey, /** @type {any} */ (widget), ...rest);
        }
    }
    return widget;
}
