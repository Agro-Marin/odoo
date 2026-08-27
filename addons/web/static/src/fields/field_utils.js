// @ts-check
/** @odoo-module native */

import { exprToBoolean } from "@web/core/utils/format/strings";

/**
 * @param {Record<string, any>} options
 * @returns {boolean}
 */
export function extractAutosave(options) {
    return "autosave" in options ? exprToBoolean(options.autosave) : true;
}

/**
 * @param {import("@web/model/relational_model/record").RelationalRecord} record
 * @param {string} fieldName
 * @returns {boolean}
 */
export const isFalseEmpty = (record, fieldName) =>
    /** @type {Record<string, any>} */ (record.data)[fieldName] === false;

/**
 * @param {unknown} value
 * @returns {number | undefined}
 */
export function parseDimensionAttr(value) {
    if (value === undefined || value === null || value === "") {
        return undefined;
    }
    const parsed = parseInt(/** @type {any} */ (value), 10);
    return Number.isNaN(parsed) ? undefined : parsed;
}

/**
 * The `enable_formatting` reading, split out because `monetary` needs it while
 * taking its input type from an ATTRIBUTE rather than from `options.type` --
 * which is why it used to carry its own copy of these three lines.
 *
 * @param {Record<string, any>} options
 * @returns {boolean}
 */
export function extractFormatNumber(options) {
    return options?.enable_formatting !== undefined
        ? Boolean(options.enable_formatting)
        : true;
}

/**
 * @param {{ options: Record<string, any> }} params
 * @returns {{ formatNumber: boolean, humanReadable: boolean, inputType: string | undefined, step: number | undefined, decimals: number }}
 */
export function extractNumericOptions({ options }) {
    return {
        formatNumber: extractFormatNumber(options),
        humanReadable: !!options.human_readable,
        inputType: options.type,
        step: options.step,
        decimals: options.decimals || 0,
    };
}

/**
 * Write a binary field and, when the arch named one through `filename=`, the
 * char field carrying the file name -- in ONE changeset, which is why this
 * cannot go through `field.update`, whose whole signature is a single key.
 *
 * The two call sites this replaces had each got one half right: the binary
 * field guarded `fileNameField in record.fields` but blanked the name to `""`,
 * a value the ORM does not treat as an empty Char; the pdf viewer blanked to
 * `false` but wrote the key even when the named field was not on the record.
 * Both halves are kept here.
 *
 * @param {import("@web/model/relational_model/record").RelationalRecord} record
 * @param {{ valueField: string, fileNameField?: string, data?: string | false, name?: string }} params
 * @returns {Promise<void>}
 */
export function updateFileValue(record, { valueField, fileNameField, data, name }) {
    /** @type {Record<string, any>} */
    const changes = { [valueField]: data || false };
    const fields = /** @type {Record<string, any>} */ (record.fields);
    if (fileNameField && fileNameField in fields) {
        const nextName = name || false;
        if (
            /** @type {Record<string, any>} */ (record.data)[fileNameField] !== nextName
        ) {
            changes[fileNameField] = nextName;
        }
    }
    return record.update(changes);
}
