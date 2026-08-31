// @ts-check
/** @odoo-module native */

import { getDomainDisplayedOperators } from "@web/components/domain_selector/domain_selector_operator_editor";

/**
 * The subset of `getDomainDisplayedOperators` that an expression can express.
 * It is an intersection, so an entry that function never returns is dead: `<=`
 * and `>=` sat here unreachable, since no branch of it yields either.
 *
 * @type {string[]}
 */
const EXPRESSION_VALID_OPERATORS = [
    "<",
    ">",
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
