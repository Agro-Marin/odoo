// @ts-check
/** @odoo-module native */

/** @module @web/core/py_js/py_interpreter - AST-walking interpreter for Python expressions used in domains and QWeb */

import { BUILTINS, EvaluationError, execOnIterable } from "./py_builtin.js";
import {
    NotSupportedError,
    PyDate,
    PyDateTime,
    PyRelativeDelta,
    PyTime,
    PyTimeDelta,
} from "./py_date.js";
import { parseArgs } from "./py_parser.js";
import { PY_DICT, toPyDict } from "./py_utils.js";

// -----------------------------------------------------------------------------
// Types
// -----------------------------------------------------------------------------

/**
 * @typedef { import("./py_parser").AST } AST
 */

// -----------------------------------------------------------------------------
// Constants and helpers
// -----------------------------------------------------------------------------

// Lazy-initialized on first call to evaluate() — avoids TDZ when
// py_builtin.js hasn't finished executing yet (native ESM circular import).
let isTrue;

/** Properties that must never be accessed via bracket or dot notation in expressions. */
const BLOCKED_PROPERTIES = new Set([
    "constructor",
    "__proto__",
    "prototype",
    "__defineGetter__",
    "__defineSetter__",
    "__lookupGetter__",
    "__lookupSetter__",
]);

/** Maximum AST evaluation depth to prevent stack overflow from crafted expressions. */
const MAX_EVAL_DEPTH = 100;

/**
 * We want to maintain this order:
 *   None < number (boolean) < dict < string < list
 * So, each type is mapped to a number to represent that order
 *
 * @param {any} val
 * @returns {number} index type
 */
function pytypeIndex(val) {
    switch (typeof val) {
        case "object":
            // None, List, Object, Dict
            return val === null ? 1 : Array.isArray(val) ? 5 : 3;
        case "number":
            return 2;
        case "string":
            return 4;
    }
    throw new EvaluationError(`Unknown type: ${typeof val}`);
}

/**
 * @param {Object} obj
 * @returns {boolean}
 */
function isConstructor(obj) {
    if (!obj.prototype) {
        return false; // arrow functions and methods have no prototype
    }
    try {
        // ES6 class constructors throw TypeError when called without `new`.
        // Reflect.construct checks [[IsClassConstructor]] without side effects.
        Reflect.construct(String, [], obj);
        return true;
    } catch {
        return false;
    }
}

/**
 * Compare two values
 *
 * @param {any} left
 * @param {any} right
 * @returns {boolean}
 */
function isLess(left, right) {
    if (typeof left === "number" && typeof right === "number") {
        return left < right;
    }
    if (typeof left === "boolean") {
        left = left ? 1 : 0;
    }
    if (typeof right === "boolean") {
        right = right ? 1 : 0;
    }
    const leftIndex = pytypeIndex(left);
    const rightIndex = pytypeIndex(right);
    if (leftIndex === rightIndex) {
        return left < right;
    }
    return leftIndex < rightIndex;
}

/**
 * @param {any} left
 * @param {any} right
 * @returns {boolean}
 */
function isEqual(left, right) {
    if (typeof left !== typeof right) {
        if (typeof left === "boolean" && typeof right === "number") {
            return right === (left ? 1 : 0);
        }
        if (typeof left === "number" && typeof right === "boolean") {
            return left === (right ? 1 : 0);
        }
        return false;
    }
    if (left instanceof Object && left.isEqual) {
        return left.isEqual(right);
    }
    if (Array.isArray(left) && Array.isArray(right)) {
        return (
            left.length === right.length && left.every((v, i) => isEqual(v, right[i]))
        );
    }
    return left === right;
}

/**
 * @param {any} left
 * @param {any} right
 * @returns {boolean}
 */
function isIn(left, right) {
    if (Array.isArray(right)) {
        // Use isEqual for value-based comparison (matches Python __eq__
        // semantics for objects like PyDate/PyDateTime).
        return right.some((item) => isEqual(left, item));
    }
    if (typeof right === "string" && typeof left === "string") {
        return right.includes(left);
    }
    if (right instanceof Set) {
        return right.has(left);
    }
    if (right != null && typeof right === "object") {
        return Object.hasOwn(right, left);
    }
    return false;
}

const DICT = {
    get(...args) {
        const { key, defValue } = parseArgs(args, ["key", "defValue"]);
        if (Object.hasOwn(this, key)) {
            return this[key];
        } else if (defValue !== undefined) {
            return defValue;
        }
        return null;
    },
};

const STRING = {
    lower() {
        return this.toLowerCase();
    },
    upper() {
        return this.toUpperCase();
    },
};

function applyFunc(key, func, set, ...args) {
    // we always receive at least one argument: kwargs (return fnValue(...args, kwargs); in FunctionCall case)
    if (args.length === 1) {
        return new Set(set);
    }
    if (args.length > 2) {
        throw new EvaluationError(
            `${key}: py_js supports at most 1 argument, got (${args.length - 1})`,
        );
    }
    return execOnIterable(args[0], func);
}

const SET = {
    /** @this {Set<any>} */
    intersection(...args) {
        return applyFunc(
            "intersection",
            (iterable) => {
                const intersection = new Set();
                for (const i of iterable) {
                    if (this.has(i)) {
                        intersection.add(i);
                    }
                }
                return intersection;
            },
            this,
            ...args,
        );
    },
    /** @this {Set<any>} */
    difference(...args) {
        return applyFunc(
            "difference",
            (iterable) => {
                iterable = new Set(iterable);
                const difference = new Set();
                for (const e of this) {
                    if (!iterable.has(e)) {
                        difference.add(e);
                    }
                }
                return difference;
            },
            this,
            ...args,
        );
    },
    /** @this {Set<any>} */
    union(...args) {
        return applyFunc(
            "union",
            (iterable) => new Set([...this, ...iterable]),
            this,
            ...args,
        );
    },
};

// -----------------------------------------------------------------------------
// Evaluate function
// -----------------------------------------------------------------------------

/**
 * @param {Function} _class the class whose methods we want
 * @returns {Function[]} an array containing the methods defined on the class,
 *  including the constructor
 */
function methods(_class) {
    return Object.getOwnPropertyNames(_class.prototype).map(
        (prop) => _class.prototype[prop],
    );
}

// Lazy-initialized on first call to evaluate() — avoids TDZ when
// py_builtin.js hasn't finished executing yet (native ESM circular import).
let allowedFns;

const unboundFn = Symbol("unbound function");

/**
 * @param {AST} ast
 * @param {Object} context
 * @returns {any}
 */
export function evaluate(ast, context = {}) {
    // Lazy-init on first call (after all modules have settled)
    if (!isTrue) {
        isTrue = BUILTINS.bool;
        allowedFns = new Set([
            BUILTINS.time.strftime,
            BUILTINS.set,
            BUILTINS.bool,
            BUILTINS.min,
            BUILTINS.max,
            BUILTINS.len,
            BUILTINS.abs,
            BUILTINS.int,
            BUILTINS.float,
            BUILTINS.str,
            BUILTINS.round,
            BUILTINS.context_today,
            BUILTINS.datetime.datetime.now,
            BUILTINS.datetime.datetime.combine,
            BUILTINS.datetime.date.today,
            ...methods(BUILTINS.relativedelta),
            ...Object.values(BUILTINS.datetime).flatMap((obj) => methods(obj)),
            ...Object.values(SET),
            ...Object.values(DICT),
            ...Object.values(STRING),
        ]);
    }
    const dicts = new Set();
    let pyContext;
    let evalDepth = 0;
    const evalContext = Object.assign(Object.create(null), context);
    if (!("context" in evalContext)) {
        Object.defineProperty(evalContext, "context", {
            get() {
                if (!pyContext) {
                    pyContext = toPyDict(context);
                }
                return pyContext;
            },
        });
    }

    /**
     * Apply a unary operator within the current evaluation scope.
     * Defined here (instead of module-level) to reuse _evaluate and dicts.
     */
    function _applyUnaryOp(ast) {
        const value = _evaluate(ast.right);
        switch (ast.op) {
            case "-":
                if (value instanceof Object && value.negate) {
                    return value.negate();
                }
                return -value;
            case "+":
                return value;
            case "not":
                return !isTrue(value);
            case "~":
                return ~value;
        }
        throw new EvaluationError(`Unknown unary operator: ${ast.op}`);
    }

    /**
     * Apply a binary operator within the current evaluation scope.
     * Defined here (instead of module-level) to reuse _evaluate and dicts.
     */
    function _applyBinaryOp(ast) {
        const left = _evaluate(ast.left);
        const right = _evaluate(ast.right);
        switch (ast.op) {
            case "+": {
                const relativeDeltaOnLeft = left instanceof PyRelativeDelta;
                const relativeDeltaOnRight = right instanceof PyRelativeDelta;
                if (relativeDeltaOnLeft || relativeDeltaOnRight) {
                    const date = relativeDeltaOnLeft ? right : left;
                    const delta = relativeDeltaOnLeft ? left : right;
                    return PyRelativeDelta.add(date, delta);
                }

                const timeDeltaOnLeft = left instanceof PyTimeDelta;
                const timeDeltaOnRight = right instanceof PyTimeDelta;
                if (timeDeltaOnLeft && timeDeltaOnRight) {
                    return left.add(right);
                }
                if (timeDeltaOnLeft) {
                    if (right instanceof PyDate || right instanceof PyDateTime) {
                        return right.add(left);
                    } else {
                        throw new NotSupportedError();
                    }
                }
                if (timeDeltaOnRight) {
                    if (left instanceof PyDate || left instanceof PyDateTime) {
                        return left.add(right);
                    } else {
                        throw new NotSupportedError();
                    }
                }
                if (Array.isArray(left) && Array.isArray(right)) {
                    return [...left, ...right];
                }

                return left + right;
            }
            case "-": {
                const isRightDelta = right instanceof PyRelativeDelta;
                if (isRightDelta) {
                    return PyRelativeDelta.subtract(left, right);
                }

                const timeDeltaOnRight = right instanceof PyTimeDelta;
                if (timeDeltaOnRight) {
                    if (left instanceof PyTimeDelta) {
                        return left.subtract(right);
                    } else if (left instanceof PyDate || left instanceof PyDateTime) {
                        return left.subtract(right);
                    } else {
                        throw new NotSupportedError();
                    }
                }

                if (left instanceof PyDate || left instanceof PyDateTime) {
                    return left.subtract(right);
                }
                return left - right;
            }
            case "*": {
                const timeDeltaOnLeft = left instanceof PyTimeDelta;
                const timeDeltaOnRight = right instanceof PyTimeDelta;
                if (timeDeltaOnLeft || timeDeltaOnRight) {
                    const number = timeDeltaOnLeft ? right : left;
                    const delta = timeDeltaOnLeft ? left : right;
                    return delta.multiply(number);
                }

                return left * right;
            }
            case "/":
                if (right === 0) {
                    throw new EvaluationError("ZeroDivisionError: division by zero");
                }
                return left / right;
            case "%":
                if (right === 0) {
                    throw new EvaluationError("ZeroDivisionError: modulo by zero");
                }
                return ((left % right) + right) % right;
            case "//":
                if (left instanceof PyTimeDelta) {
                    return left.divide(right);
                }
                if (right === 0) {
                    throw new EvaluationError(
                        "ZeroDivisionError: floor division by zero",
                    );
                }
                return Math.floor(left / right);
            case "**":
                return left ** right;
            case "==":
                return isEqual(left, right);
            case "<>":
            case "!=":
                return !isEqual(left, right);
            case "<":
                return isLess(left, right);
            case ">":
                return isLess(right, left);
            case ">=":
                return isEqual(left, right) || isLess(right, left);
            case "<=":
                return isEqual(left, right) || isLess(left, right);
            case "in":
                return isIn(left, right);
            case "not in":
                return !isIn(left, right);
            case "is":
                return left === null ? right === null : left === right;
            case "is not":
                return left === null ? right !== null : left !== right;
            case "|":
                return left | right;
            case "^":
                return left ^ right;
            case "&":
                return left & right;
            case "<<":
                return left << right;
            case ">>":
                return left >> right;
        }
        throw new EvaluationError(`Unknown binary operator: ${ast.op}`);
    }

    function _innerEvaluate(ast) {
        if (++evalDepth > MAX_EVAL_DEPTH) {
            throw new EvaluationError("Maximum expression depth exceeded");
        }
        try {
            switch (ast.type) {
                case 0 /* Number */:
                case 1 /* String */:
                    return ast.value;
                case 5 /* Name */:
                    if (ast.value in evalContext) {
                        return evalContext[ast.value];
                    } else if (ast.value in BUILTINS) {
                        return BUILTINS[ast.value];
                    } else {
                        throw new EvaluationError(`Name '${ast.value}' is not defined`);
                    }
                case 3 /* None */:
                    return null;
                case 2 /* Boolean */:
                    return ast.value;
                case 6 /* UnaryOperator */:
                    return _applyUnaryOp(ast);
                case 7 /* BinaryOperator */:
                    return _applyBinaryOp(ast);
                case 14 /* BooleanOperator */: {
                    const left = _evaluate(ast.left);
                    if (ast.op === "and") {
                        return isTrue(left) ? _evaluate(ast.right) : left;
                    } else {
                        return isTrue(left) ? left : _evaluate(ast.right);
                    }
                }
                case 4 /* List */:
                case 10 /* Tuple */:
                    return ast.value.map(_evaluate);
                case 11 /* Dictionary */: {
                    const dict = {};
                    for (const key of Object.keys(ast.value || {})) {
                        dict[key] = _evaluate(ast.value[key]);
                    }
                    dicts.add(dict);
                    return dict;
                }
                case 8 /* FunctionCall */: {
                    const fnValue = _evaluate(ast.fn);
                    const args = ast.args.map(_evaluate);
                    const kwargs = {};
                    for (const kwarg of Object.keys(ast.kwargs || {})) {
                        kwargs[kwarg] = _evaluate(ast.kwargs[kwarg]);
                    }
                    if (
                        fnValue === PyDate ||
                        fnValue === PyDateTime ||
                        fnValue === PyTime ||
                        fnValue === PyRelativeDelta ||
                        fnValue === PyTimeDelta
                    ) {
                        return fnValue.create(...args, kwargs);
                    }
                    return fnValue(...args, kwargs);
                }
                case 12 /* Lookup */: {
                    const dict = _evaluate(ast.target);
                    const key = _evaluate(ast.key);
                    if (BLOCKED_PROPERTIES.has(key)) {
                        throw new EvaluationError(`Access to '${key}' is forbidden`);
                    }
                    return dict[key];
                }
                case 13 /* If */: {
                    if (isTrue(_evaluate(ast.condition))) {
                        return _evaluate(ast.ifTrue);
                    } else {
                        return _evaluate(ast.ifFalse);
                    }
                }
                case 15 /* ObjLookup */: {
                    let left = _evaluate(ast.obj);
                    let result;
                    if (dicts.has(left) || Object.isPrototypeOf.call(PY_DICT, left)) {
                        // this is a dictionary => need to apply dict methods
                        result = DICT[ast.key];
                    } else if (typeof left === "string") {
                        result = STRING[ast.key];
                    } else if (left instanceof Set) {
                        result = SET[ast.key];
                    } else if (ast.key === "get" && typeof left === "object") {
                        result = DICT[ast.key];
                        left = toPyDict(left);
                    } else {
                        if (BLOCKED_PROPERTIES.has(ast.key)) {
                            throw new EvaluationError(
                                `Access to '${ast.key}' is forbidden`,
                            );
                        }
                        result = left[ast.key];
                    }
                    if (typeof result === "function") {
                        if (!isConstructor(result)) {
                            const bound = result.bind(left);
                            bound[unboundFn] = result;
                            return bound;
                        }
                    }
                    return result;
                }
            }
            throw new EvaluationError(`AST of type ${ast.type} cannot be evaluated`);
        } finally {
            evalDepth--;
        }
    }

    /**
     * @param {AST} ast
     */
    function _evaluate(ast) {
        const val = _innerEvaluate(ast);
        if (
            typeof val === "function" &&
            !allowedFns.has(val) &&
            !allowedFns.has(val[unboundFn])
        ) {
            throw new Error("Invalid Function Call");
        }
        return val;
    }
    return _evaluate(ast);
}
