// @ts-check
/** @odoo-module native */

/** @import { Value } from "./condition_tree.js" */

/**
 * @param {Value} value
 * @param {boolean | Record<number, string>} [displayNames]
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
 * @returns {boolean}
 */
export function isId(value) {
    return Number.isInteger(value) && /** @type {number} */ (value) >= 1;
}

/**
 * @param {Record<string, any>|null} fieldDef
 * @returns {string|null}
 */
export function getResModel(fieldDef) {
    if (fieldDef) {
        return fieldDef.is_property ? fieldDef.comodel : fieldDef.relation;
    }
    return null;
}

/**
 * @type {string[]}
 */
const SPECIAL_FIELDS = [
    "country_id",
    "user_id",
    "partner_id",
    "step_id",
    "stage_id",
    "id",
];

/**
 * @param {Record<string, Record<string, any>>} fieldDefs
 * @returns {string}
 * @throws {Error}
 */
export function getDefaultPath(fieldDefs) {
    for (const name of SPECIAL_FIELDS) {
        if (fieldDefs[name]) {
            return name;
        }
    }
    const name = Object.keys(fieldDefs)[0];
    if (name) {
        return name;
    }
    throw new Error(`No field found`);
}
