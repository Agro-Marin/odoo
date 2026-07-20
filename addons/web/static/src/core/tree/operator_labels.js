// @ts-check
/** @odoo-module native */

/** @module @web/core/tree/operator_labels - Operator descriptions, labels, and serialization for domain condition trees */

import { _t } from "@web/core/l10n/translation";
import { parseExpr } from "@web/core/py_js/py";

import { formatValue, toValue } from "./condition_tree.js";

/** @type {Record<string, string|Function>} */
export const OPERATOR_DESCRIPTIONS = {
    // valid operators (see TERM_OPERATORS in expression.py)
    "=": (/** @type {string} */ fieldDefType) => {
        switch (fieldDefType) {
            case "many2one":
            case "many2many":
            case "one2many":
                return _t("=");
            default:
                return _t("is equal to");
        }
    },
    "!=": (/** @type {string} */ fieldDefType) => {
        switch (fieldDefType) {
            case "many2one":
            case "many2many":
            case "one2many":
                return _t("!=");
            default:
                return _t("is not equal to");
        }
    },
    "<=": _t("lower or equal to"),
    "<": (/** @type {string} */ fieldDefType) => {
        switch (fieldDefType) {
            case "date":
            case "datetime":
                return _t("before");
            default:
                return _t("lower than");
        }
    },
    ">": (/** @type {string} */ fieldDefType) => {
        switch (fieldDefType) {
            case "date":
            case "datetime":
                return _t("after");
            default:
                return _t("greater than");
        }
    },
    ">=": _t("greater or equal to"),
    "=?": "=?",
    "=like": _t("=like"),
    "=ilike": _t("=ilike"),
    like: _t("like"),
    "not like": _t("not like"),
    ilike: _t("contains"),
    "not ilike": _t("does not contain"),
    in: (/** @type {string} */ fieldDefType) => {
        switch (fieldDefType) {
            case "many2one":
            case "many2many":
            case "one2many":
                return _t("is equal to");
            default:
                return _t("is in");
        }
    },
    "not in": (/** @type {string} */ fieldDefType) => {
        switch (fieldDefType) {
            case "many2one":
            case "many2many":
            case "one2many":
                return _t("is not equal to");
            default:
                return _t("is not in");
        }
    },
    child_of: _t("child of"),
    parent_of: _t("parent of"),
    any: (/** @type {string} */ fieldDefType) => {
        switch (fieldDefType) {
            case "many2one":
                return _t("matches");
            default:
                return _t("match");
        }
    },
    "not any": (/** @type {string} */ fieldDefType) => {
        switch (fieldDefType) {
            case "many2one":
                return _t("matches none of");
            default:
                return _t("match none of");
        }
    },

    // virtual operators
    set: _t("is set"),
    "not set": _t("is not set"),

    "starts with": _t("starts with"),

    between: _t("between"),
    "in range": _t("is in"),
};

/**
 * @param {import("./condition_tree").Value} operator
 * @param {boolean} [negate=false]
 * @returns {string} serialized key for operator+negate combination
 */
export function toKey(operator, negate = false) {
    if (
        !negate &&
        typeof operator === "string" &&
        Object.hasOwn(OPERATOR_DESCRIPTIONS, operator)
    ) {
        // main case; keep it simple
        return operator;
    }
    return JSON.stringify([formatValue(operator), negate]);
}

/**
 * @param {string} key
 * @returns {[import("./condition_tree").Value, boolean]} operator and negate flag
 */
export function toOperator(key) {
    // Invariant (see toKey): the JSON-serialized form is always a
    // `JSON.stringify([...])` — it starts with "[" — while the plain form is
    // an operator from OPERATOR_DESCRIPTIONS, none of which starts with "[".
    if (!key.startsWith("[")) {
        return [key, false];
    }
    const [expr, negate] = JSON.parse(key);
    return [toValue(parseExpr(expr)), negate];
}

/**
 * @param {string} operator
 * @param {string} [fieldDefType]
 * @returns {string|undefined} human-readable operator description
 */
function getOperatorDescription(operator, fieldDefType) {
    const description = OPERATOR_DESCRIPTIONS[operator];
    if (typeof description === "function") {
        return description(fieldDefType);
    }
    return description;
}

/**
 * @param {import("./condition_tree").Value} operator
 * @param {string} [fieldDefType]
 * @param {boolean} [negate=false]
 * @param {(operator: string, fieldDefType?: string) => string|null} [getDescr]
 * @returns {string} display label for the operator
 */
export function getOperatorLabel(
    operator,
    fieldDefType,
    negate = false,
    getDescr = (operator, fieldDefType) => null,
) {
    let label;
    if (
        typeof operator === "string" &&
        Object.hasOwn(OPERATOR_DESCRIPTIONS, operator)
    ) {
        label =
            getDescr(operator, fieldDefType) ||
            getOperatorDescription(operator, fieldDefType) ||
            formatValue(operator);
    } else {
        label = formatValue(operator);
    }
    if (negate) {
        return _t(`not %(operator_label)s`, { operator_label: label });
    }
    return label;
}

/**
 * @param {import("./condition_tree").Value} operator
 * @param {string} [fieldDefType]
 * @param {boolean} [negate=false]
 * @returns {[string, string]} key and label pair
 */
export function getOperatorInfo(operator, fieldDefType, negate = false) {
    const key = toKey(operator, negate);
    const label = getOperatorLabel(operator, fieldDefType, negate);
    return [key, label];
}
