// @ts-check
/** @odoo-module native */

/** @module @web/core/tree/virtual_operators - Introduces and eliminates virtual operators (between, in range, any/all) in condition trees */

/** @import { Tree, Options, Condition, Connector, Value } from "./condition_tree.js" */

import {
    applyTransformations,
    areEqualTrees,
    cloneTree,
    condition,
    connector,
    expression,
    FALSE_TREE,
    isTree,
    normalizeValue,
    operate,
    rewriteNConsecutiveChildren,
    TRUE_TREE,
} from "./condition_tree.js";

/**
 * @param {Value} path
 */
function splitPath(path) {
    const pathParts = typeof path === "string" ? path.split(".") : [];
    const lastPart = pathParts.pop() || "";
    const initialPath = pathParts.join(".");
    return { initialPath, lastPart };
}

/**
 * @param {Value} path
 */
function isSimplePath(path) {
    return typeof path === "string" && !splitPath(path).initialPath;
}

/**
 * @param {Tree} tree
 * @param {string} initialPath
 * @param {boolean} negate
 */
function wrapInAny(tree, initialPath, negate) {
    let con = cloneTree(tree);
    if (initialPath) {
        con = condition(initialPath, "any", con);
    }
    /** @type {any} */ (con).negate = negate;
    return con;
}

/**
 * @param {Tree} tree
 * @param {Options} [options]
 */
function introduceSetOperators(tree, options = {}) {
    /**
     * @param {Condition} c
     * @param {Options} [options]
     */
    function _introduceSetOperator(c, options = {}) {
        const { negate, path, operator, value } = c;
        const fieldType = /** @type {any} */ (options.getFieldDef?.(path))?.type;
        if (["=", "!="].includes(/** @type {string} */ (operator))) {
            if (fieldType) {
                if (fieldType === "boolean" && value === true) {
                    return condition(
                        path,
                        operator === "=" ? "set" : "not set",
                        value,
                        negate,
                    );
                } else if (
                    !["many2one", "date", "datetime"].includes(fieldType) &&
                    value === false
                ) {
                    return condition(
                        path,
                        operator === "=" ? "not set" : "set",
                        value,
                        negate,
                    );
                }
            }
        }
    }
    return operate(_introduceSetOperator, tree, options);
}

/**
 * @param {Tree} tree
 */
function eliminateSetOperators(tree) {
    /**
     * @param {Condition} c
     */
    function _removeSetOperator(c) {
        const { negate, path, operator, value } = c;
        if (["set", "not set"].includes(/** @type {string} */ (operator))) {
            if (value === true) {
                return condition(path, operator === "set" ? "=" : "!=", value, negate);
            }
            return condition(path, operator === "set" ? "!=" : "=", value, negate);
        }
    }
    return operate(_removeSetOperator, tree);
}

/**
 * @param {Tree} tree
 * @param {Options} options
 */
function introduceStartsWithOperators(tree, options) {
    /**
     * @param {Condition} c
     * @param {Options} options
     */
    function _introduceStartsWithOperator(c, options) {
        const { negate, path, operator, value } = c;
        const fieldType = /** @type {any} */ (options.getFieldDef?.(path))?.type;
        if (
            ["char", "text", "html"].includes(fieldType) &&
            operator === "=ilike" &&
            typeof value === "string"
        ) {
            if (value.endsWith("%")) {
                return condition(path, "starts with", value.slice(0, -1), negate);
            }
        }
    }
    return operate(_introduceStartsWithOperator, tree, options);
}

/**
 * @param {Tree} tree
 */
function eliminateStartsWithOperators(tree) {
    /**
     * @param {Condition} c
     */
    function _eliminateStartsWithOperator(c) {
        const { negate, path, operator, value } = c;
        if (operator === "starts with") {
            return condition(path, "=ilike", `${value}%`, negate);
        }
    }
    return operate(_eliminateStartsWithOperator, tree);
}

/**
 * @param {Tree} c
 * @returns {c is Connector}
 */
function isSimpleAnd(c) {
    if (
        c.type === "connector" &&
        c.value === "&" &&
        !c.negate &&
        c.children.length === 2 &&
        c.children.every((child) => child.type === "condition" && !child.negate)
    ) {
        return true;
    }
    return false;
}

/**
 * @param {Tree} c
 */
function isBetween(c) {
    if (isSimpleAnd(c)) {
        const [
            { path: p1, operator: op1, value: value1 },
            { path: p2, operator: op2, value: value2 },
        ] = /** @type {Condition[]} */ (c.children);
        if (p1 === p2 && op1 === ">=" && op2 === "<=") {
            return { path: p1, value1, value2 };
        }
    }
    return false;
}

/**
 * @param {Value} path
 * @param {Value} value1
 * @param {Value} value2
 */
function makeBetween(path, value1, value2) {
    return connector("&", [
        condition(path, ">=", value1),
        condition(path, "<=", value2),
    ]);
}

/**
 * @param {Tree} c
 */
function isStrictBetween(c) {
    if (isSimpleAnd(c)) {
        const [
            { path: p1, operator: op1, value: value1 },
            { path: p2, operator: op2, value: value2 },
        ] = /** @type {Condition[]} */ (c.children);
        if (p1 === p2 && op1 === ">=" && op2 === "<") {
            return { path: p1, value1, value2 };
        }
    }
    return false;
}

/**
 * @param {Value} path
 * @param {Value} value1
 * @param {Value} value2
 */
function makeStrictBetween(path, value1, value2) {
    return connector("&", [
        condition(path, ">=", value1),
        condition(path, "<", value2),
    ]);
}

/**
 * @param {string} delta
 */
function boundDate(delta) {
    if (!delta) {
        return expression(`context_today().strftime("%Y-%m-%d")`);
    }
    return expression(
        `(context_today() + relativedelta(${delta})).strftime('%Y-%m-%d')`,
    );
}

/**
 * @param {string} delta
 */
function boundDatetime(delta) {
    if (!delta) {
        return expression(
            `datetime.datetime.combine(context_today(), datetime.time(0, 0, 0)).to_utc().strftime("%Y-%m-%d %H:%M:%S")`,
        );
    }
    return expression(
        `datetime.datetime.combine(context_today() + relativedelta(${delta}), datetime.time(0, 0, 0)).to_utc().strftime("%Y-%m-%d %H:%M:%S")`,
    );
}

const BOUNDS_SMART_DATES = [
    ["today", "today", "today +1d"],
    ["last 7 days", "today -7d", "today"],
    ["last 30 days", "today -30d", "today"],
    ["month to date", "today =1d", "today +1d"],
    ["last month", "today =1d -1m", "today =1d"],
    ["year to date", "today =1m =1d", "today +1d"],
    ["last 12 months", "today =1d -12m", "today =1d"],
];
const DELTAS = [
    ["today", "", "days = 1"],
    ["last 7 days", "days = -7", ""],
    ["last 30 days", "days = -30", ""],
    ["month to date", "day = 1", "days = 1"],
    ["last month", "day = 1, months = -1", "day = 1"],
    ["year to date", "day = 1, month = 1", "days = 1"],
    ["last 12 months", "day = 1, months = -12", "day = 1"],
];
const BOUNDS_DATE = DELTAS.map(([k, l, r]) => [k, boundDate(l), boundDate(r)]);
const BOUNDS_DATETIME = DELTAS.map(([k, l, r]) => [
    k,
    boundDatetime(l),
    boundDatetime(r),
]);

/**
 * @param {boolean | undefined} generateSmartDates
 * @param {string} fieldType
 */
function getBounds(generateSmartDates, fieldType) {
    return generateSmartDates
        ? BOUNDS_SMART_DATES
        : fieldType === "date"
          ? BOUNDS_DATE
          : BOUNDS_DATETIME;
}

/**
 * @param {Tree} tree
 * @param {Options} [options]
 */
function introduceInRangeOperators(tree, options = {}) {
    /**
     * @param {Tree} c
     * @param {Options} options
     */
    function _introduceInRangeOperator(c, options) {
        const res1 = isStrictBetween(c);
        if (res1) {
            const generateSmartDates =
                "generateSmartDates" in options ? options.generateSmartDates : true;
            // @ts-ignore
            const { path, value1, value2 } = res1;
            const fieldType = /** @type {any} */ (options.getFieldDef?.(path))?.type;
            if (["date", "datetime"].includes(fieldType) && isSimplePath(path)) {
                const bounds = getBounds(generateSmartDates, fieldType);
                for (const [valueType, leftBound, rightBound] of bounds) {
                    if (
                        generateSmartDates
                            ? value1 === leftBound && value2 === rightBound
                            : /** @type {any} */ (value1)._expr ===
                                  /** @type {any} */ (leftBound)._expr &&
                              /** @type {any} */ (value2)._expr ===
                                  /** @type {any} */ (rightBound)._expr
                    ) {
                        return condition(path, "in range", [
                            fieldType,
                            valueType,
                            false,
                            false,
                        ]);
                    }
                }
            }
        }
        const res2 = isBetween(c);
        if (res2) {
            // @ts-ignore
            const { path, value1, value2 } = res2;
            const fieldType = /** @type {any} */ (options.getFieldDef?.(path))?.type;
            if (["date", "datetime"].includes(fieldType) && isSimplePath(path)) {
                return condition(path, "in range", [
                    fieldType,
                    "custom range",
                    // @ts-ignore
                    ...normalizeValue([value1, value2]),
                ]);
            }
        }
    }
    return operate(
        rewriteNConsecutiveChildren(_introduceInRangeOperator),
        tree,
        options,
        "connector",
    );
}

/**
 * @param {Tree} tree
 * @param {Options} [options]
 */
function eliminateInRangeOperators(tree, options = {}) {
    /**
     * @param {Condition} c
     * @param {Options} options
     */
    function _eliminateInRangeOperator(c, options) {
        const { negate, path, operator, value } = c;
        // @ts-ignore
        if (operator !== "in range") {
            return;
        }
        const { initialPath, lastPart } = splitPath(path);
        const [fieldType, valueType, value1, value2] = /** @type {any} */ (value);
        let tree;
        if (valueType === "custom range") {
            tree = makeBetween(lastPart, value1, value2);
        } else {
            const generateSmartDates =
                "generateSmartDates" in options ? options.generateSmartDates : true;
            const bounds = getBounds(generateSmartDates, fieldType);
            const found = bounds.find(([v]) => v === valueType);
            if (!found) {
                return; // unknown valueType — leave condition untouched
            }
            const [, leftBound, rightBound] = found;
            tree = makeStrictBetween(lastPart, leftBound, rightBound);
        }
        return wrapInAny(tree, initialPath, negate);
    }
    return operate(_eliminateInRangeOperator, tree, options);
}

/**
 * @param {Tree} tree
 * @param {Options} [options]
 */
function introduceBetweenOperators(tree, options = {}) {
    /**
     * @param {Tree} c
     * @param {Options} options
     */
    function _introduceBetweenOperator(c, options) {
        const res = isBetween(c);
        if (!res) {
            return;
        }
        // @ts-ignore
        const { path, value1, value2 } = res;
        const fieldType = /** @type {any} */ (options.getFieldDef?.(path))?.type;
        if (
            ["integer", "float", "monetary"].includes(fieldType) &&
            isSimplePath(path)
        ) {
            return condition(
                path,
                "between",
                normalizeValue(/** @type {any} */ ([value1, value2])),
            );
        }
    }
    return operate(
        rewriteNConsecutiveChildren(_introduceBetweenOperator),
        tree,
        options,
        "connector",
    );
}

/**
 * @param {Tree} tree
 */
function eliminateBetweenOperators(tree) {
    /**
     * @param {Condition} c
     */
    function _eliminateBetweenOperator(c) {
        const { negate, path, operator, value } = c;
        // @ts-ignore
        if (operator !== "between") {
            return;
        }
        const { initialPath, lastPart } = splitPath(path);
        return wrapInAny(
            makeBetween(
                lastPart,
                /** @type {any} */ (value)[0],
                /** @type {any} */ (value)[1],
            ),
            initialPath,
            negate,
        );
    }
    return operate(_eliminateBetweenOperator, tree);
}

/**
 * @param {Condition} c
 */
function _eliminateAnyOperator(c) {
    const { path, operator, value, negate } = c;
    const condValue = /** @type {Condition} */ (value);
    if (
        operator === "any" &&
        isTree(value) &&
        condValue.type === "condition" &&
        typeof path === "string" &&
        typeof condValue.path === "string" &&
        !negate &&
        !condValue.negate &&
        ["between", "in range"].includes(/** @type {string} */ (condValue.operator))
    ) {
        return condition(
            `${path}.${condValue.path}`,
            condValue.operator,
            condValue.value,
        );
    }
}

/**
 * @param {Tree} tree
 */
function eliminateAnyOperators(tree) {
    return operate(_eliminateAnyOperator, tree);
}

/**
 * @param {Tree} tree
 */
function removeFalseTrueLeaves(tree) {
    /**
     * @param {Condition} c
     */
    function _removeFalseTrueLeave(c) {
        const { path, operator, value, negate } = c;
        if (areEqualTrees(condition(path, operator, value), FALSE_TREE)) {
            return connector(negate ? "&" : "|", []);
        }
        if (areEqualTrees(condition(path, operator, value), TRUE_TREE)) {
            return connector(negate ? "|" : "&", []);
        }
    }
    return operate(_removeFalseTrueLeave, tree);
}

/**
 * Transform a raw condition tree by introducing virtual operators (between, in-range,
 * starts-with, any/all set operators) where the raw domain operators match their patterns.
 * Call before rendering the tree in a UI tree editor.
 * @param {Tree} tree
 * @param {Options} [options={}]
 * @returns {Tree}
 */
// Patchable object for functions that need to be extended by other modules.
// ESM namespace objects are non-configurable, so patch() cannot redefine
// their properties. This object provides a patchable indirection layer.
// The exported functions below delegate to this object, so patching it
// affects ALL consumers — even those using direct named imports.
export const virtualOperatorFunctions = {
    /**
     * @param {Tree} tree
     * @param {Options} [options]
     */
    introduceVirtualOperators(tree, options = {}) {
        // Ordering contract (applyTransformations runs the array in order):
        // the introduce* passes must run BEFORE eliminateAnyOperators, which
        // collapses the between/in-range conditions they create out of `any`
        // wrappers; in-range detection must also see raw >=/< pairs before
        // between rewrites them.
        return applyTransformations(
            [
                introduceInRangeOperators,
                introduceBetweenOperators,
                introduceStartsWithOperators,
                introduceSetOperators,
                eliminateAnyOperators,
            ],
            tree,
            options,
        );
    },
    /**
     * @param {Tree} tree
     * @param {Options} [options]
     */
    eliminateVirtualOperators(tree, options = {}) {
        // Ordering contract (applyTransformations runs the array in order):
        // the reverse of introduceVirtualOperators — set operators go last,
        // mirroring how they were introduced.
        return applyTransformations(
            [
                eliminateSetOperators,
                eliminateStartsWithOperators,
                eliminateBetweenOperators,
                eliminateInRangeOperators,
            ],
            tree,
            options,
        );
    },
};

/**
 * @param {Tree} tree
 * @param {Options} [options]
 */
export function introduceVirtualOperators(tree, options = {}) {
    return virtualOperatorFunctions.introduceVirtualOperators(tree, options);
}

/**
 * Convert virtual operators back to standard domain operators.
 * Reverses `introduceVirtualOperators`. Call before converting a tree to a domain string.
 * @param {Tree} tree
 * @param {Options} [options={}]
 * @returns {Tree}
 */
export function eliminateVirtualOperators(tree, options = {}) {
    return virtualOperatorFunctions.eliminateVirtualOperators(tree, options);
}

/**
 * Return whether two trees represent the same logical domain, normalising away
 * virtual-operator representations (between, in-range, etc.) before comparing.
 * @param {Tree} tree
 * @param {Tree} otherTree
 * @returns {boolean}
 */

export function areEquivalentTrees(tree, otherTree) {
    const simplifiedTree = removeFalseTrueLeaves(eliminateVirtualOperators(tree));
    const otherSimplifiedTree = removeFalseTrueLeaves(
        eliminateVirtualOperators(otherTree),
    );
    return areEqualTrees(simplifiedTree, otherSimplifiedTree);
}
