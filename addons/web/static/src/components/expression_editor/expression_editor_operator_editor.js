// @ts-check
/** @odoo-module native */

import { getDomainDisplayedOperators } from "@web/components/domain_selector/domain_selector_operator_editor";

/** @type {string[]} */
const EXPRESSION_VALID_OPERATORS = [
    "<",
    "<=",
    ">",
    ">=",
    "between",
    "in range",
    "in",
    "not in",
    "=",
    "!=",
    "set",
    "not set",
];

/**
 * @param {Object} fieldDef
 * @returns {string[]}
 */
export function getExpressionDisplayedOperators(fieldDef) {
    const operators = getDomainDisplayedOperators(fieldDef);
    return operators.filter((operator) =>
        EXPRESSION_VALID_OPERATORS.includes(operator),
    );
}
