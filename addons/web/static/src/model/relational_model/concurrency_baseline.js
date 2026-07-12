// @ts-check
/** @odoo-module native */

/** @module @web/model/relational_model/concurrency_baseline - Shared builder for the field-scoped optimistic-locking baseline (known_values) */

/**
 * Field types whose value cannot be safely compared for the field-scoped
 * optimistic lock, so they never contribute a baseline:
 * - x2many/binary/html/json/properties/reference: no stable scalar to compare;
 * - date/datetime: client (Luxon, tz/ms) vs raw DB value risks a
 *   timezone-boundary FALSE conflict.
 * Mirrors the server's `_CONCURRENCY_SAFE_TYPES` exclusion set
 * (models/web_read.py) — kept in one place on each side so they can't drift.
 */
const NON_COMPARABLE_TYPES = new Set([
    "one2many",
    "many2many",
    "binary",
    "html",
    "date",
    "datetime",
    "json",
    "properties",
    "reference",
]);

/**
 * Build the field-scoped optimistic-locking baseline for `record`: the
 * originally-loaded value (`record._values`) of each field in `fieldNames`
 * that can be safely compared server-side. Shared by the single-save
 * (`record_save.js`) and list mass-edit (`dynamic_list.js`) paths so their
 * exclusion rules never diverge — the server fails open on anything omitted.
 *
 * @param {import("./record").RelationalRecord} record
 * @param {Iterable<string>} fieldNames the fields being written
 * @returns {Record<string, any>} `{ field: baseline }` (may be empty)
 */
export function buildConcurrencyBaseline(record, fieldNames) {
    /** @type {Record<string, any>} */
    const baseline = {};
    for (const fieldName of fieldNames) {
        const field = record.fields[fieldName];
        if (
            !field?.type ||
            NON_COMPARABLE_TYPES.has(field.type) ||
            // jsonb-backed columns: the server-side raw read returns a
            // per-lang / per-company dict, never comparable to the scalar the
            // client read — the server skips them, so don't send them.
            field.translate ||
            field.company_dependent
        ) {
            continue;
        }
        const value = record._values[fieldName];
        // A selection with a genuine integer-0 option is ambiguous: the
        // deserializer maps BOTH server `false` (unset → DB NULL) and server
        // `0` (the 0-option) to client `0`, and the server coerces NULL to ""
        // but 0 to "0". Sending `0` as the baseline for an originally-unset
        // field would raise a spurious conflict on every save. Skip it — the
        // server fails open (no baseline = no check).
        if (
            field.type === "selection" &&
            value === 0 &&
            field.selection?.some((opt) => opt[0] === 0)
        ) {
            continue;
        }
        baseline[fieldName] = value;
    }
    return baseline;
}
