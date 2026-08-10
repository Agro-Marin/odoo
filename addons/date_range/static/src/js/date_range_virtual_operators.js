/** @odoo-module native */
import {
    condition,
    connector,
    normalizeValue,
    operate,
    rewriteNConsecutiveChildren,
} from "@web/core/tree";

/**
 * Check if a tree node is a date range pattern (field <= end AND field >= start).
 *
 * The `<=` bound comes first on purpose. The web client's own
 * `introduceInRangeOperators` runs before this one and claims the natural
 * `>= … <=` order for its "in range" operator, so a date range has to be
 * recognisable by the mirrored order or the two would fight over the same
 * pair. `date.range.get_domain()` emits this order for the same reason.
 *
 * @param {Object} c - Tree node to check
 * @returns {Object|false} Object with {path, value1, value2} if match, false otherwise
 */
function isDateRange(c) {
    if (
        c.type === "connector" &&
        c.value === "&" &&
        !c.negate &&
        c.children.length === 2 &&
        c.children.every((child) => child.type === "condition" && !child.negate)
    ) {
        const [
            {path: p1, operator: op1, value: value1},
            {path: p2, operator: op2, value: value2},
        ] = c.children;

        if (p1 === p2 && op1 === "<=" && op2 === ">=") {
            return {path: p1, value1, value2};
        }
    }
    return false;
}

/**
 * Introduce date range operators by converting adjacent <= and >= conditions.
 *
 * Converts `field <= end AND field >= start` on a date or datetime field into
 * a single `field daterange [end, start]` condition, so the UI can offer a
 * period selector instead of two date inputs.
 *
 * The operator produced is always the generic `daterange`. A typed
 * `daterange_<typeId>` is a choice the user made in the editor; a domain does
 * not record it, and it must not be guessed. An earlier version read the
 * selected option out of the first `<select>` element on the page to recover
 * it, which made the result depend on unrelated DOM that happened to be
 * mounted. The value editor matches the stored dates against the known ranges,
 * so the right period stays selected without the operator carrying its type.
 *
 * @param {Object} tree - Condition tree to process
 * @param {Object} [options={}] - Processing options
 * @param {Function} [options.getFieldDef] - Function to get field definitions
 * @returns {Object} Tree with date range operators introduced
 */
export function introduceDateRangeOperators(tree, options = {}) {
    function _introduceDateRangeOperator(c, opts) {
        const res = isDateRange(c);
        if (!res) {
            return;
        }
        const {path, value1, value2} = res;
        const fieldType = opts.getFieldDef?.(path)?.type;
        if (["date", "datetime"].includes(fieldType)) {
            return condition(path, "daterange", normalizeValue([value1, value2]));
        }
    }

    return operate(
        rewriteNConsecutiveChildren(_introduceDateRangeOperator),
        tree,
        options,
        "connector"
    );
}

/**
 * Eliminate date range operators by converting them back to standard <= and >=.
 *
 * Converts `field daterange [end, start]` into
 * `field <= end AND field >= start` before the tree is turned into a domain.
 *
 * @param {Object} tree - Condition tree to process
 * @param {Object} [options={}] - Processing options
 * @returns {Object} Tree with date range operators eliminated
 */
export function eliminateDateRangeOperators(tree, options = {}) {
    function _eliminateDateRangeOperator(c) {
        const {negate, path, operator, value} = c;

        // `operate` only ever hands us conditions, but a condition's operator
        // is not necessarily a string (it can be an expression in debug mode),
        // so the type check has to come before any string method.
        if (typeof operator !== "string" || !operator.includes("daterange")) {
            return;
        }
        if (!Array.isArray(value) || value.length !== 2) {
            return;
        }

        return connector(
            "&",
            [
                condition(path, "<=", value[0]), // value[0] is the end date
                condition(path, ">=", value[1]), // value[1] is the start date
            ],
            negate
        );
    }

    return operate(_eliminateDateRangeOperator, tree, options);
}
