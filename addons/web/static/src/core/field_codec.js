// @ts-check
/** @odoo-module native */

/** @module @web/core/field_codec - Unified per-field-type value codec: one complete {format, parse} descriptor per field type, composed from the formatters and parsers registries */

import { registry } from "@web/core/registry";

/**
 * A single, complete value codec for one field type.
 *
 * A *facade*, not a fourth source of truth: ``format``/``parse`` resolve
 * their backing function from the ``formatters``/``parsers`` registries at
 * call time, so third-party overrides (including late-loaded bundles) are
 * honored automatically and can never disagree with the codec.
 *
 * Closes the asymmetry those registries leave open (22 formatters vs. only
 * 8 parsers, so char/selection/boolean/relational types etc. had no parser
 * and every widget re-implemented parsing inline) by exposing BOTH
 * directions for every type.
 *
 * @typedef {object} FieldCodec
 * @property {(value: any, options?: Record<string, any>) => string} format
 *   Render a stored value to its display string. Delegates to the
 *   ``formatters`` registry entry for the type; unknown types render via
 *   ``String(value)`` (empty string for ``false`` / nullish).
 * @property {(value: string, options?: Record<string, any>) => any} parse
 *   Convert user input back to a stored value: types with a registered parser
 *   (date, datetime, float, float_time, integer, many2one_reference, monetary,
 *   percentage) delegate to it; every other type returns the value unchanged
 *   (for char/text/html the string IS the value; for picker-origin types the
 *   widget already supplies a native value). This is the type *default* only —
 *   option-driven parsing such as char's optional ``trim`` belongs to the
 *   widget (see ``CharField``), which is why it is not baked in here.
 * @property {(fieldInfo: any) => Record<string, any>} extractOptions
 *   Derive display options for this type from an arch field-info node (``{attrs,
 *   options}``), by delegating to the underlying formatter's optional
 *   ``extractOptions`` static — returns ``{}`` when the formatter declares none.
 *   Lets call sites build format options without duck-typing the raw formatter
 *   function (``if (formatter.extractOptions) …``).
 * @property {(value: any, field?: any) => any} deserialize
 *   Convert a raw server value into its client representation (the inverse of
 *   ``serialize``). Reads the ``deserializers`` registry that the model layer
 *   populates. Pass the field def for types whose conversion needs it
 *   (``selection`` reads ``field.selection``; ``properties`` recurses).
 *   DISTINCT from ``parse``: this is wire→client transport, not input→value.
 * @property {(value: any) => any} serialize
 *   Convert a client value into its server wire format (the inverse of
 *   ``deserialize``). Reads the ``serializers`` registry. Note the intentional
 *   read-rich/write-lean asymmetry (e.g. ``many2one`` deserializes to
 *   ``{id, display_name}`` but serializes back to just the id). DISTINCT from
 *   ``format``: this is client→wire transport, not value→display.
 * @property {boolean} parseable
 *   ``true`` when the type round-trips text → value (registered-parser types
 *   plus char/text/html), ``false`` when the value originates from a non-text
 *   widget. Lets callers decide whether to treat user text as authoritative.
 *   The flag — not the ``parse`` behaviour — is what distinguishes char/text
 *   (identity parse, but parseable) from selection/boolean (identity, not).
 */

const formatters = registry.category("formatters");
const parsers = registry.category("parsers");
// Transport conversion (server <-> client), registered by the model layer
// (`@web/model/relational_model/field_values` + `record_value_transforms`).
// The registry is the neutral interface both sides read, so they can never
// diverge. DISTINCT from format/parse: serialize(many2one) is the id,
// format(many2one) is the name.
const serializers = registry.category("serializers");
const deserializers = registry.category("deserializers");

/**
 * Free-text types: parseable via identity (no registered parser needed), so
 * ``parseable`` is what distinguishes them from picker-origin types like
 * selection/boolean. Whitespace handling (char's ``trim`` option) is a
 * per-field widget concern, not done here.
 */
const TEXT_TYPES = new Set(["char", "text", "html"]);

/**
 * Last-resort formatter for unknown types: render as a string.
 * @param {unknown} value
 */
const formatUnknown = (value) =>
    value == null || value === false ? "" : String(value);

/**
 * Per-type codec cache. Cached closures read the registries live, so there
 * is no staleness to invalidate. Plain ``Map`` rather than
 * ``@web/core/utils/functions.memoize`` (keys solely on first argument).
 *
 * @type {Map<string, FieldCodec>}
 */
const codecCache = new Map();

/**
 * Return the unified value codec for a field type.
 *
 * Always returns a complete codec (both ``format`` and ``parse`` defined) for
 * every type, and never throws: an unknown type formats via ``String(value)``
 * and parses as identity.
 *
 * @param {string} type field type (``"char"``, ``"integer"``, ``"many2one"``, …)
 * @returns {FieldCodec}
 */
export function getFieldCodec(type) {
    const cached = codecCache.get(type);
    if (cached) {
        return cached;
    }
    /** @type {FieldCodec} */
    const codec = {
        format: (value, options) => formatters.get(type, formatUnknown)(value, options),
        parse: (value, options) =>
            parsers.contains(type) ? parsers.get(type)(value, options) : value,
        extractOptions: (fieldInfo) => {
            // Formatters may carry an optional `extractOptions`; the registry
            // item shape types them as bare functions, so reach for it via any.
            const fn = /** @type {any} */ (formatters.get(type, formatUnknown));
            return fn.extractOptions ? fn.extractOptions(fieldInfo) : {};
        },
        deserialize: (value, field) =>
            deserializers.get(type, (v) => v)(value, field ?? { type }),
        serialize: (value) => serializers.get(type, (v) => v)(value),
        get parseable() {
            return parsers.contains(type) || TEXT_TYPES.has(type);
        },
    };
    codecCache.set(type, codec);
    return codec;
}

/**
 * Whether a field type has any value-codec coverage (i.e. a registered
 * formatter). ``getFieldCodec`` still returns a usable codec for types where
 * this is ``false`` — it just falls back to string formatting / identity
 * parsing.
 *
 * @param {string} type
 * @returns {boolean}
 */
export function hasFieldCodec(type) {
    return formatters.contains(type);
}
