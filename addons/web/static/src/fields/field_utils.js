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
