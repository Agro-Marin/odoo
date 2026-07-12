// @ts-check
/** @odoo-module native */

/** @module @web/core/tree/utils - Shared helpers for value disambiguation, ID checking, model resolution, and default paths */

/** @import { Value } from "./condition_tree.js" */

/**
 * Determine whether a value is ambiguous and needs explicit typing.
 * Returns true when a value mixes strings/IDs with other types or contains empty strings.
 * @param {Value} value
 * @param {boolean | Record<number, string>} [displayNames] - truthy means IDs
 *   should be treated as strings; a non-empty display-names map is also
 *   accepted (the function only uses ``displayNames`` for truthiness).
 * @returns {boolean}
 */
export function disambiguate(value, displayNames) {
    if (!Array.isArray(value)) {
        return value === "";
    }
    let hasSomeString = false;
    let hasSomethingElse = false;
    for (const val of value) {
        if (val === "") {
            return true;
        }
        if (typeof val === "string" || (displayNames && isId(val))) {
            hasSomeString = true;
        } else {
            hasSomethingElse = true;
        }
    }
    return hasSomeString && hasSomethingElse;
}

/**
 * @param {unknown} value
 * @returns {boolean} whether the value is a positive integer (valid record ID)
 */
export function isId(value) {
    return Number.isInteger(value) && /** @type {number} */ (value) >= 1;
}

/**
 * Extract the related model name from a field definition.
 * @param {Record<string, any>|null} fieldDef
 * @returns {string|null}
 */
export function getResModel(fieldDef) {
    if (fieldDef) {
        return fieldDef.is_property ? fieldDef.comodel : fieldDef.relation;
    }
    return null;
}

// ``step_id`` is preferred ahead of ``stage_id`` because this fork renames
// ``project.task.stage_id`` -> ``step_id``; ``stage_id`` is kept because many
// other models (crm.lead, ...) still use it, so it remains a sensible default.
/** @type {string[]} */
const SPECIAL_FIELDS = [
    "country_id",
    "user_id",
    "partner_id",
    "step_id",
    "stage_id",
    "id",
];

/**
 * Pick a sensible default field path from a set of field definitions.
 * Prefers well-known relational fields, falls back to the first available field.
 * @param {Record<string, Record<string, any>>} fieldDefs
 * @returns {string}
 * @throws {Error} if no fields exist
 */
export function getDefaultPath(fieldDefs) {
    for (const name of SPECIAL_FIELDS) {
        const fieldDef = fieldDefs[name];
        if (fieldDef) {
            return fieldDef.name;
        }
    }
    const name = Object.keys(fieldDefs)[0];
    if (name) {
        return name;
    }
    throw new Error(`No field found`);
}
