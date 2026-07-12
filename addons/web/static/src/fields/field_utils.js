// @ts-check
/** @odoo-module native */

/** @module @web/fields/field_utils - Shared utilities for field extractProps and configuration */

import { exprToBoolean } from "@web/core/utils/format/strings";

/**
 * Shared ``autosave`` option extraction for fields that persist immediately on
 * edit (boolean_toggle, boolean_favorite, priority, state_selection, color).
 * The option defaults to ``true`` when unset — matching each widget's
 * ``defaultProps.autosave = true``, so a props-only instantiation (no
 * ``extractProps``) still persists instead of silently swallowing the write.
 *
 * @param {Record<string, any>} options
 * @returns {boolean}
 */
export function extractAutosave(options) {
    return "autosave" in options ? exprToBoolean(options.autosave) : true;
}

/**
 * Shared ``isEmpty`` predicate for field descriptors whose widget treats the
 * ORM ``false`` sentinel as "no value" (numeric and selection-like fields).
 *
 * @param {import("@web/model/relational_model/record").RelationalRecord} record
 * @param {string} fieldName
 * @returns {boolean}
 */
export const isFalseEmpty = (record, fieldName) => record.data[fieldName] === false;

/**
 * Parse a raw XML dimension attribute (e.g. ``width="90"``) into a number for a
 * Number-typed prop. Returns ``undefined`` for absent or non-numeric values so
 * OWL prop validation doesn't trip on a leftover attribute string in dev.
 *
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
 * The digits parameter is available as both an XML attribute (JSON string)
 * and a widget option (array). The attribute takes precedence.
 *
 * @param {{ attrs: Record<string, any>, options: Record<string, any> }} params
 * @returns {number[] | undefined}
 */
export function extractDigits({ attrs, options }) {
    if (attrs.digits) {
        try {
            return JSON.parse(attrs.digits);
        } catch {
            // A malformed `digits` XML attribute must not crash the field
            // render; fall through to the option/undefined path.
        }
    }
    if (options.digits) {
        return options.digits;
    }
    return undefined;
}

/**
 * Extract numeric field props shared by float and integer fields (formatting
 * toggle, human-readable mode, input type, step size, decimal precision) to
 * avoid duplicating them across both extractProps.
 *
 * @param {{ options: Record<string, any> }} params
 * @returns {{ formatNumber: boolean, humanReadable: boolean, inputType: string | undefined, step: number | undefined, decimals: number }}
 */
export function extractNumericOptions({ options }) {
    return {
        formatNumber:
            options?.enable_formatting !== undefined
                ? Boolean(options.enable_formatting)
                : true,
        humanReadable: !!options.human_readable,
        inputType: options.type,
        step: options.step,
        decimals: options.decimals || 0,
    };
}
