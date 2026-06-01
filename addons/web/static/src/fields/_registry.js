// @ts-check
/** @odoo-module native */

/** @module @web/fields/_registry - Central registration helper for field widgets, with optional typed-spec overload */

import { registry } from "@web/core/registry";

/**
 * Known top-level view prefixes used by view-specific widget variants.
 *
 * Six prefixes are in active use across the fork (verified by grep of
 * ``registerField("<prefix>.<name>", ...)`` call sites as of 2026-05-25):
 * the five canonical view types — ``list``, ``form``, ``kanban``,
 * ``calendar``, ``hierarchy`` — plus the settings-form pseudo-view
 * ``base_settings``, which the ``settings`` view's arch parser passes as
 * its ``viewType`` argument when resolving radio / binary variants.
 *
 * Constraining the typed-API ``view`` field to this union catches typos
 * at IDE / tsc-noEmit time. Addons declaring a NEW view prefix should
 * either widen this union here or fall back to the legacy string form
 * (``registerField("myview.mywidget", ...)``).
 *
 * @typedef {"list" | "form" | "kanban" | "calendar" | "hierarchy" | "base_settings"} FieldViewPrefix
 */

/**
 * Typed spec for a field-widget registration. Use this object form
 * instead of a pre-composed string when a widget registers under a
 * view-prefixed key — typos in ``view`` become a compile-time error
 * via the {@link FieldViewPrefix} union.
 *
 * - ``name`` is the widget identifier the view arch references via
 *   ``widget="<name>"`` (e.g. ``"many2one"``, ``"res_partner_many2one"``).
 *   It is NOT necessarily the field type — ``res_partner_many2one`` is a
 *   widget name, not a type. See ``getFieldFromRegistry`` for the
 *   widget-vs-type fallback logic at lookup time.
 *
 * - ``view`` is the optional view prefix; omitting it registers the
 *   default (view-agnostic) variant.
 *
 * - ``aliases`` is an optional list of additional keys that should map
 *   to the SAME widget object as the primary registration. Each entry
 *   may be a legacy string key (``"code"``) or a nested
 *   {@link FieldRegistrationSpec} (``{ name: "one2many", view: "calendar" }``).
 *   Use this ONLY when the same widget instance is the intended target
 *   for every key. For view-variant widgets that share a base but
 *   customize behaviour (e.g. ``many2ManyTagsField`` for kanban vs.
 *   ``many2ManyTagsFieldColorEditable`` for form), make a separate
 *   {@link registerField} call with the variant widget — chaining via
 *   ``aliases`` would silently bind the variant key to the base widget.
 *   Nested ``aliases`` on alias entries are ignored: aliases form a
 *   flat set, not a tree.
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
 * 1. **Legacy string form** — backward-compatible with the 94 existing
 *    call sites:
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
 *    The alias form is intentionally limited to the same-widget case;
 *    a variant widget (different component, different ``extractProps``)
 *    must use its own call so the registration site reads as a deliberate
 *    new variant, not a side effect.
 *
 * Returns the widget so call sites stay one-liners and downstream
 * addons can chain (``const w = registerField(spec, widget);``).
 *
 * Historical note: an earlier revision (commit 253cf3d8d38) maintained
 * a parallel ``FIELD_WIDGETS`` Map alongside the live registry, with a
 * "drift detector" test asserting ``FIELD_WIDGETS ⊆ registry``. The
 * Map was scaffolding for promised downstream tooling (.d.ts
 * generation, audit scripts, debug inspectors) that never materialized
 * — the debug inspector that did land
 * (``webclient/debug/field_widgets_dialog.js``) reads the registry
 * directly anyway. The drift test was structurally guaranteed to
 * pass because the only writer of the Map was this function, which
 * always wrote both halves on the same line. Map and test removed in
 * favor of a smaller surface; if a real downstream consumer emerges
 * later, the Map can be reintroduced alongside that consumer rather
 * than as speculative scaffolding.
 *
 * @template T
 * @param {string | FieldRegistrationSpec} nameOrSpec - Registry key
 *   (legacy string form, e.g. ``"char"``, ``"list.text"``,
 *   ``"kanban.progressbar"``) or a typed spec.
 * @param {T} widget - Widget descriptor with component, displayName,
 *   supportedTypes, …
 * @param {...unknown} rest - Forwarded to ``registry.add`` (e.g.
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
