// @ts-check
/** @odoo-module native */

/** @module @web/fields/field_utils - Shared utilities for field extractProps and configuration */

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
