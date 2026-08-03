// @ts-check
/** @odoo-module native */

/** @module @web/model/relational_model/concurrency_baseline */

const NON_COMPARABLE_TYPES = new Set([
    "one2many",
    "many2many",
    "binary",
    "html",
    "date",
    "datetime",
    "json",
    "properties",
    "properties_definition",
    "reference",
    "many2one_reference",
]);

/**
 * Declared against the record CONTRACT rather than `RelationalRecord`: this
 * reads two members (`fields`, `_values`), and saying so makes reaching for a
 * third a typecheck failure instead of a silent entry in the private-access
 * budget. See `record_contract.js`.
 *
 * @param {import("./record_contract").RecordContract} record
 * @param {Iterable<string>} fieldNames
 * @returns {Record<string, any>}
 */
export function buildConcurrencyBaseline(record, fieldNames) {
    /** @type {Record<string, any>} */
    const baseline = {};
    for (const fieldName of fieldNames) {
        const field = record.fields[fieldName];
        if (
            !field?.type ||
            NON_COMPARABLE_TYPES.has(field.type) ||
            field.translate ||
            field.company_dependent
        ) {
            continue;
        }
        const value = /** @type {Record<string, any>} */ (record._values)[fieldName];
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

/**
 * @param {import("./record").RelationalRecord[]} records
 * @param {Iterable<string>} fieldNames
 * @param {Record<string, any>} kwargs
 * @returns {Record<string, any>}
 */
export function buildKnownValuesKwargs(records, fieldNames, kwargs) {
    /** @type {Record<string, any>} */
    const knownValues = {};
    for (const record of records) {
        if (!record.resId) {
            continue;
        }
        const baseline = buildConcurrencyBaseline(record, fieldNames);
        if (Object.keys(baseline).length) {
            knownValues[record.resId] = baseline;
        }
    }
    return Object.keys(knownValues).length
        ? { ...kwargs, known_values: knownValues }
        : kwargs;
}
