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
import { ASTType } from "./ast_type.js";

// -----------------------------------------------------------------------------
// Types
// -----------------------------------------------------------------------------

/**
 * AST node walked by the interpreter — a discriminated union keyed on the
 * literal ``type`` tag (see {@link ASTType}); ``switch (ast.type)`` narrows each
 * case to its concrete node shape.
 * @typedef {import("./ast_type.js").AST} AST
 */

// -----------------------------------------------------------------------------
// Constants and helpers
// -----------------------------------------------------------------------------

// Lazy-initialized on first call to evaluate() — avoids TDZ when
// py_builtin.js hasn't finished executing yet (native ESM circular import).
/** @type {(value?: any) => boolean} */
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
 * @param {Function} obj
 * @returns {boolean}
 */
function isConstructor(obj) {
    return !!obj.prototype && !!obj.prototype.constructor.name;
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
        return right.includes(left);
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
    /**
     * @this {Record<string, any>}
     * @param {...any} args
     * @returns {any}
     */
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
    /** @this {string} */
    lower() {
        return this.toLowerCase();
    },
    /** @this {string} */
    upper() {
        return this.toUpperCase();
    },
};

/**
 * @param {string} key
 * @param {Function} func
 * @param {Set<any>} set
 * @param {...any} args
 * @returns {any}
 */
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
    /**
     * @this {Set<any>}
     * @param {...any} args
     */
    intersection(...args) {
        return applyFunc(
            "intersection",
            (/** @type {Iterable<any>} */ iterable) => {
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
    /**
     * @this {Set<any>}
     * @param {...any} args
     */
    difference(...args) {
        return applyFunc(
            "difference",
            (/** @type {any} */ iterable) => {
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
    /**
     * @this {Set<any>}
     * @param {...any} args
     */
    union(...args) {
        return applyFunc(
            "union",
            (/** @type {Iterable<any>} */ iterable) => new Set([...this, ...iterable]),
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
/** @type {Set<any>} */
let allowedFns;

const unboundFn = Symbol("unbound function");

/**
 * @param {AST} ast
 * @param {Record<string, any>} context
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
    /** @type {any} */
    let pyContext;
    let evalDepth = 0;
    // Name resolution reads directly from ``context`` rather than from a
    // null-proto *copy* of it. The previous implementation ran
    // ``Object.assign(Object.create(null), context)`` on every ``evaluate``
    // call, which is O(number-of-keys) — and a record's eval context carries
    // every field value (see ``RelationalRecord._setEvalContext``), so a
    // single modifier like ``state == 'draft'`` paid to shallow-copy ~50
    // unrelated fields per record per render. Reading from ``context``
    // directly makes a name lookup O(1) and removes the per-call allocation.
    //
    // Two invariants of the old copy are preserved explicitly in the Name
    // case below:
    //   • null-proto semantics — name resolution uses ``Object.hasOwn`` so a
    //     name like ``toString``/``constructor`` never resolves to an
    //     inherited ``Object.prototype`` member; it falls through to a
    //     builtin or raises, exactly as before.
    //   • the lazy ``context`` self-reference — referencing ``context`` in an
    //     expression yields ``toPyDict(context)`` UNLESS the caller supplied
    //     its own ``context`` key, in which case the caller's value wins.
    const callerProvidesContext = Object.hasOwn(context, "context");

    /**
     * Apply a unary operator within the current evaluation scope.
     * Defined here (instead of module-level) to reuse _evaluate and dicts.
     * @param {import("./ast_type.js").ASTUnaryOperator} ast
     * @returns {any}
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
     * @param {import("./ast_type.js").ASTBinaryOperator} ast
     * @returns {any}
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
                    throw new EvaluationError("ZeroDivisionError: floor division by zero");
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

    /**
     * @param {AST} ast
     * @returns {any}
     */
    function _innerEvaluate(ast) {
        if (++evalDepth > MAX_EVAL_DEPTH) {
            throw new EvaluationError("Maximum expression depth exceeded");
        }
        try {
        switch (ast.type) {
            case ASTType.Number:
            case ASTType.String:
                return ast.value;
            case ASTType.Name: {
                const name = ast.value;
                if (name === "context" && !callerProvidesContext) {
                    if (!pyContext) {
                        pyContext = toPyDict(context);
                    }
                    return pyContext;
                }
                if (Object.hasOwn(context, name)) {
                    return context[name];
                } else if (name in BUILTINS) {
                    return (/** @type {Record<string, any>} */ (BUILTINS))[name];
                } else {
                    throw new EvaluationError(`Name '${name}' is not defined`);
                }
            }
            case ASTType.None:
                return null;
            case ASTType.Boolean:
                return ast.value;
            case ASTType.UnaryOperator:
                return _applyUnaryOp(ast);
            case ASTType.BinaryOperator:
                return _applyBinaryOp(ast);
            case ASTType.BooleanOperator: {
                const left = _evaluate(ast.left);
                if (ast.op === "and") {
                    return isTrue(left) ? _evaluate(ast.right) : left;
                } else {
                    return isTrue(left) ? left : _evaluate(ast.right);
                }
            }
            case ASTType.List:
            case ASTType.Tuple:
                return ast.value.map(_evaluate);
            case ASTType.Dictionary: {
                /** @type {Record<string, any>} */
                const dict = {};
                for (const key of Object.keys(ast.value || {})) {
                    dict[key] = _evaluate(ast.value[key]);
                }
                dicts.add(dict);
                return dict;
            }
            case ASTType.FunctionCall: {
                const fnValue = _evaluate(ast.fn);
                const args = ast.args.map(_evaluate);
                /** @type {Record<string, any>} */
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
            case ASTType.Lookup: {
                const dict = _evaluate(ast.target);
                const key = _evaluate(ast.key);
                if (BLOCKED_PROPERTIES.has(key)) {
                    throw new EvaluationError(`Access to '${key}' is forbidden`);
                }
                return dict[key];
            }
            case ASTType.If: {
                if (isTrue(_evaluate(ast.condition))) {
                    return _evaluate(ast.ifTrue);
                } else {
                    return _evaluate(ast.ifFalse);
                }
            }
            case ASTType.ObjLookup: {
                let left = _evaluate(ast.obj);
                let result;
                if (dicts.has(left) || Object.isPrototypeOf.call(PY_DICT, left)) {
                    // this is a dictionary => need to apply dict methods
                    result = (/** @type {Record<string, any>} */ (DICT))[ast.key];
                } else if (typeof left === "string") {
                    result = (/** @type {Record<string, any>} */ (STRING))[ast.key];
                } else if (left instanceof Set) {
                    result = (/** @type {Record<string, any>} */ (SET))[ast.key];
                } else if (ast.key === "get" && typeof left === "object") {
                    result = (/** @type {Record<string, any>} */ (DICT))[ast.key];
                    left = toPyDict(left);
                } else {
                    if (BLOCKED_PROPERTIES.has(ast.key)) {
                        throw new EvaluationError(`Access to '${ast.key}' is forbidden`);
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
     * @returns {any}
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
