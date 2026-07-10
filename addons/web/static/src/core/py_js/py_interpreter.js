// @ts-check
/** @odoo-module native */

/** @module @web/core/py_js/py_interpreter - AST-walking interpreter for Python expressions used in domains and QWeb */

import { ASTType } from "./ast_type.js";
import { bindArgs } from "./py_args.js";
import {
    BUILTINS,
    EvaluationError,
    execOnIterable,
    pyRepr,
    pyStr,
} from "./py_builtin.js";
import {
    NotSupportedError,
    PyDate,
    PyDateTime,
    PyRelativeDelta,
    PyTime,
    PyTimeDelta,
} from "./py_date.js";
import { PY_DICT, toPyDict } from "./py_utils.js";

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
 * Order: None < number (boolean) < dict < string < list. Each type maps to
 * an index representing that order.
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
    // Typed Py* objects (PyDate, PyTimeDelta, ...) carry their own equality.
    // Guard with a typeof check so a plain context dict that happens to have an
    // ``isEqual`` key (a data value, not a method) doesn't get called.
    if (left instanceof Object && typeof left.isEqual === "function") {
        return left.isEqual(right);
    }
    if (Array.isArray(left) || Array.isArray(right)) {
        if (!Array.isArray(left) || !Array.isArray(right)) {
            return false;
        }
        return (
            left.length === right.length && left.every((v, i) => isEqual(v, right[i]))
        );
    }
    if (left instanceof Set || right instanceof Set) {
        if (
            !(left instanceof Set) ||
            !(right instanceof Set) ||
            left.size !== right.size
        ) {
            return false;
        }
        for (const v of left) {
            let found = false;
            for (const w of right) {
                if (isEqual(v, w)) {
                    found = true;
                    break;
                }
            }
            if (!found) {
                return false;
            }
        }
        return true;
    }
    if (
        left !== null &&
        right !== null &&
        typeof left === "object" &&
        typeof right === "object"
    ) {
        // Plain dicts: deep-compare own enumerable keys. If either side exposes
        // a custom ``isEqual`` method it's a typed Py* object, not a dict.
        if (typeof left.isEqual === "function" || typeof right.isEqual === "function") {
            return false;
        }
        const leftKeys = Object.keys(left);
        const rightKeys = Object.keys(right);
        if (leftKeys.length !== rightKeys.length) {
            return false;
        }
        return leftKeys.every(
            (k) => Object.hasOwn(right, k) && isEqual(left[k], right[k]),
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
        // Python ``in`` uses ``==`` per element, so deep-compare (``[1,2] in
        // [[1,2]]`` is True) rather than JS strict ``includes``.
        return right.some((x) => isEqual(left, x));
    }
    if (typeof right === "string" && typeof left === "string") {
        return right.includes(left);
    }
    if (right instanceof Set) {
        for (const x of right) {
            if (isEqual(left, x)) {
                return true;
            }
        }
        return false;
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
        const { key, defValue } = bindArgs(args, ["key", "defValue"]);
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

/**
 * Apply a unary operator.
 * @param {import("./ast_type.js").ASTUnaryOperator} ast
 * @param {(ast: AST) => any} recurse evaluator for sub-expressions
 * @returns {any}
 */
function _applyUnaryOp(ast, recurse) {
    const value = recurse(ast.right);
    switch (ast.op) {
        case "-":
            // typeof guard: a plain data dict may carry a `negate` KEY (a
            // data value, not a method) — same precedent as `isEqual` above.
            if (value instanceof Object && typeof value.negate === "function") {
                return value.negate();
            }
            if (typeof value !== "number" && typeof value !== "boolean") {
                throw new EvaluationError(
                    `bad operand type for unary -: '${pyTypeName(value)}'`,
                );
            }
            return -value;
        case "+":
            // Python defines __pos__ for numbers, bools and timedelta only.
            if (
                typeof value !== "number" &&
                typeof value !== "boolean" &&
                !(value instanceof PyTimeDelta)
            ) {
                throw new EvaluationError(
                    `bad operand type for unary +: '${pyTypeName(value)}'`,
                );
            }
            return value;
        case "not":
            return !isTrue(value);
        case "~":
            if (typeof value !== "number" && typeof value !== "boolean") {
                throw new EvaluationError(
                    `bad operand type for unary ~: '${pyTypeName(value)}'`,
                );
            }
            return ~value;
    }
    throw new EvaluationError(`Unknown unary operator: ${ast.op}`);
}

/**
 * Python-ish type name for error messages.
 * @param {any} value
 * @returns {string}
 */
function pyTypeName(value) {
    if (value === null || value === undefined) {
        return "NoneType";
    }
    if (Array.isArray(value)) {
        return "list";
    }
    switch (typeof value) {
        case "boolean":
            return "bool";
        case "number":
            return Number.isInteger(value) ? "int" : "float";
        case "string":
            return "str";
        case "object":
            return value.constructor?.name || "object";
        default:
            return typeof value;
    }
}

/**
 * Reject non-numeric operands with a Python-style TypeError message instead
 * of letting JS coercion silently produce NaN (Python bools are ints, so
 * booleans are accepted).
 *
 * @param {string} op operator symbol, for the error message
 * @param {any} value
 */
function assertNumericOperand(op, value) {
    if (typeof value !== "number" && typeof value !== "boolean") {
        throw new EvaluationError(
            `unsupported operand type(s) for ${op}: '${pyTypeName(value)}'`,
        );
    }
}

/**
 * @param {string} op operator symbol, for the error message
 * @param {any} left
 * @param {any} right
 */
function assertNumericOperands(op, left, right) {
    if (
        (typeof left !== "number" && typeof left !== "boolean") ||
        (typeof right !== "number" && typeof right !== "boolean")
    ) {
        throw new EvaluationError(
            `unsupported operand type(s) for ${op}: '${pyTypeName(left)}' and '${pyTypeName(right)}'`,
        );
    }
}

/**
 * printf-style ``%`` formatting for strings (``'%s' % val`` /
 * ``'%s=%d' % (a, b)``). Supports the conversions that show up in real Odoo
 * expressions: s, r, d/i, f, e/g, x/X, o and the ``%%`` literal, with optional
 * flags / width / precision.
 *
 * @param {string} fmt
 * @param {any} value single value or a tuple (array) of values
 * @returns {string}
 */
function pyStringFormat(fmt, value) {
    const values = Array.isArray(value) ? value.slice() : [value];
    let i = 0;
    return fmt.replace(
        /%(?:\((\w+)\))?([-+ #0]*)(\d+)?(?:\.(\d+))?([sriduxXofeEgG%])/g,
        (m, mapKey, flags, width, prec, conv) => {
            if (conv === "%") {
                return "%";
            }
            let arg;
            if (mapKey != null) {
                arg = value?.[mapKey];
            } else {
                if (i >= values.length) {
                    throw new EvaluationError("not enough arguments for format string");
                }
                arg = values[i++];
            }
            let str;
            switch (conv) {
                case "s":
                    str = pyStr(arg);
                    break;
                case "r":
                    str = pyRepr(arg);
                    break;
                case "d":
                case "i":
                case "u":
                    str = String(Math.trunc(Number(arg)));
                    break;
                case "f":
                case "e":
                case "E":
                case "g":
                case "G": {
                    const p = prec != null ? Number(prec) : 6;
                    str =
                        conv === "f"
                            ? Number(arg).toFixed(p)
                            : conv === "e" || conv === "E"
                              ? Number(arg).toExponential(p)
                              : String(Number(arg));
                    if (conv === "E" || conv === "G") {
                        str = str.toUpperCase();
                    }
                    break;
                }
                case "x":
                    str = Math.trunc(Number(arg)).toString(16);
                    break;
                case "X":
                    str = Math.trunc(Number(arg)).toString(16).toUpperCase();
                    break;
                case "o":
                    str = Math.trunc(Number(arg)).toString(8);
                    break;
                default:
                    str = pyStr(arg);
            }
            if (width) {
                const w = Number(width);
                str = flags.includes("-")
                    ? str.padEnd(w)
                    : str.padStart(w, flags.includes("0") ? "0" : " ");
            }
            return str;
        },
    );
}

/**
 * Apply a binary operator.
 * @param {import("./ast_type.js").ASTBinaryOperator} ast
 * @param {(ast: AST) => any} recurse evaluator for sub-expressions
 * @returns {any}
 */
function _applyBinaryOp(ast, recurse) {
    const left = recurse(ast.left);
    const right = recurse(ast.right);
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
            // str + str and numeric + numeric only. Python raises TypeError on
            // ``'a' + 1``; JS would silently coerce to "a1", so reject it.
            if (typeof left === "string" && typeof right === "string") {
                return left + right;
            }
            const leftNumeric = typeof left === "number" || typeof left === "boolean";
            const rightNumeric =
                typeof right === "number" || typeof right === "boolean";
            if (leftNumeric && rightNumeric) {
                return left + right;
            }
            throw new EvaluationError(
                `unsupported operand type(s) for +: '${pyTypeName(left)}' and '${pyTypeName(right)}'`,
            );
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
            assertNumericOperands("-", left, right);
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

            // Python sequence repetition: str * int and list * int (either
            // order). ``'ab' * 2`` → "abab", ``[1] * 3`` → [1, 1, 1].
            const leftSeq = typeof left === "string" || Array.isArray(left);
            const rightSeq = typeof right === "string" || Array.isArray(right);
            if (leftSeq !== rightSeq) {
                const seq = leftSeq ? left : right;
                const count = leftSeq ? right : left;
                const n = Math.max(0, Math.trunc(Number(count)));
                if (typeof seq === "string") {
                    return seq.repeat(n);
                }
                const result = [];
                for (let k = 0; k < n; k++) {
                    result.push(...seq);
                }
                return result;
            }

            assertNumericOperands("*", left, right);
            return left * right;
        }
        case "/":
            if (left instanceof PyTimeDelta) {
                if (right instanceof PyTimeDelta) {
                    // Python: td / td → float ratio.
                    const divisor = right.toMicroseconds();
                    if (divisor === 0) {
                        throw new EvaluationError(
                            "ZeroDivisionError: division by zero",
                        );
                    }
                    return left.toMicroseconds() / divisor;
                }
                assertNumericOperand("/", right);
                if (Number(right) === 0) {
                    throw new EvaluationError("ZeroDivisionError: division by zero");
                }
                // Python: td / n → timedelta (rounded to the microsecond).
                return left.divideTrue(Number(right));
            }
            assertNumericOperands("/", left, right);
            // Number(): Python bools are ints, so `1 / False` divides by zero.
            if (Number(right) === 0) {
                throw new EvaluationError("ZeroDivisionError: division by zero");
            }
            return left / right;
        case "%": {
            if (typeof left === "string") {
                // printf-style string formatting: ``'%s' % 5`` → "5".
                return pyStringFormat(left, right);
            }
            if (left instanceof PyTimeDelta && right instanceof PyTimeDelta) {
                // Python: td % td → timedelta (sign follows the divisor).
                const rus = right.toMicroseconds();
                if (rus === 0) {
                    throw new EvaluationError("ZeroDivisionError: modulo by zero");
                }
                const lus = left.toMicroseconds();
                return PyTimeDelta.create({ microseconds: ((lus % rus) + rus) % rus });
            }
            assertNumericOperands("%", left, right);
            if (Number(right) === 0) {
                throw new EvaluationError("ZeroDivisionError: modulo by zero");
            }
            return ((left % right) + right) % right;
        }
        case "//":
            if (left instanceof PyTimeDelta) {
                if (right instanceof PyTimeDelta) {
                    // Python: td // td → int.
                    const divisor = right.toMicroseconds();
                    if (divisor === 0) {
                        throw new EvaluationError(
                            "ZeroDivisionError: integer division or modulo by zero",
                        );
                    }
                    return Math.floor(left.toMicroseconds() / divisor);
                }
                assertNumericOperand("//", right);
                if (Number(right) === 0) {
                    throw new EvaluationError(
                        "ZeroDivisionError: integer division or modulo by zero",
                    );
                }
                return left.divide(Number(right));
            }
            assertNumericOperands("//", left, right);
            if (Number(right) === 0) {
                throw new EvaluationError(
                    "ZeroDivisionError: integer division or modulo by zero",
                );
            }
            return Math.floor(left / right);
        case "**":
            assertNumericOperands("**", left, right);
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
    // Name resolution reads directly from ``context`` rather than a null-proto
    // *copy* of it — the previous ``Object.assign(Object.create(null), context)``
    // per ``evaluate`` call was O(fields), and a record's eval context carries
    // every field (see ``RelationalRecord._setEvalContext``), so a single
    // modifier like ``state == 'draft'`` paid to copy ~50 unrelated fields per
    // render. Reading ``context`` directly is O(1) with no per-call allocation.
    //
    // Two invariants of the old copy are preserved explicitly in the Name case:
    //   • null-proto semantics — ``Object.hasOwn`` so a name like
    //     ``toString``/``constructor`` never resolves via ``Object.prototype``;
    //     it falls through to a builtin or raises, as before.
    //   • the lazy ``context`` self-reference — referencing ``context`` yields
    //     ``toPyDict(context)`` unless the caller supplied its own ``context``
    //     key, in which case the caller's value wins.
    const callerProvidesContext = Object.hasOwn(context, "context");

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
                        return /** @type {Record<string, any>} */ (BUILTINS)[name];
                    } else {
                        throw new EvaluationError(`Name '${name}' is not defined`);
                    }
                }
                case ASTType.None:
                    return null;
                case ASTType.Boolean:
                    return ast.value;
                case ASTType.UnaryOperator:
                    return _applyUnaryOp(ast, _evaluate);
                case ASTType.BinaryOperator:
                    return _applyBinaryOp(ast, _evaluate);
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
                        // defineProperty: keeps a literal '__proto__' key as a
                        // plain OWN entry (matching the parser side) while the
                        // dict stays a regular Object for downstream consumers
                        // (OWL props validation, deepCopy, ...).
                        Object.defineProperty(dict, key, {
                            value: _evaluate(ast.value[key]),
                            writable: true,
                            enumerable: true,
                            configurable: true,
                        });
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
                    if (
                        typeof key === "number" &&
                        key < 0 &&
                        (typeof dict === "string" || Array.isArray(dict))
                    ) {
                        // Python negative indexing (``lst[-1]`` → last element). JS
                        // bracket access returns undefined for negative indices, so
                        // use ``.at`` which counts from the end.
                        return dict.at(key);
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
                        result = /** @type {Record<string, any>} */ (DICT)[ast.key];
                    } else if (typeof left === "string") {
                        result = /** @type {Record<string, any>} */ (STRING)[ast.key];
                    } else if (left instanceof Set) {
                        result = /** @type {Record<string, any>} */ (SET)[ast.key];
                    } else if (ast.key === "get" && typeof left === "object") {
                        result = /** @type {Record<string, any>} */ (DICT)[ast.key];
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
