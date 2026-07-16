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
    pyTypeName,
} from "./py_builtin.js";
import { isEqual, isIn, isLess } from "./py_compare.js";
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

// Maximum AST evaluation depth to prevent stack overflow from crafted
// expressions. Kept in lock-step with MAX_PARSE_DEPTH (py_parser.js): the
// evaluator walks the AST recursively, so anything the parser's own recursion
// guard accepts (≤ MAX_PARSE_DEPTH nested nodes) must also be evaluable — a
// lower cap here would reject genuinely nested input the parser produced.
const MAX_EVAL_DEPTH = 200;

/**
 * @param {Function} obj
 * @returns {boolean}
 */
function isConstructor(obj) {
    return !!obj.prototype && !!obj.prototype.constructor.name;
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

// Read-only string methods mirroring the safe-eval-legal subset of Python's
// str API. Every method receives the interpreter's trailing kwargs object as
// its last argument (see the FunctionCall case), hence the bindArgs calls.
const STRING = {
    /** @this {string} */
    lower() {
        return this.toLowerCase();
    },
    /** @this {string} */
    upper() {
        return this.toUpperCase();
    },
    /** @this {string} */
    capitalize() {
        return this.charAt(0).toUpperCase() + this.slice(1).toLowerCase();
    },
    /**
     * ASCII approximation of str.title(): a word is a run of letters, so any
     * non-letter (digit, apostrophe, ...) starts a new word, as in Python
     * ("it's 2b".title() → "It'S 2B").
     * @this {string}
     */
    title() {
        return this.replace(
            /[a-zA-Z]+/g,
            (word) => word[0].toUpperCase() + word.slice(1).toLowerCase(),
        );
    },
    /**
     * @this {string}
     * @param {...any} args
     */
    strip(...args) {
        const { chars } = bindArgs(args, ["chars"]);
        if (chars === undefined || chars === null) {
            return this.trim();
        }
        if (typeof chars !== "string") {
            throw new EvaluationError("strip arg must be None or str");
        }
        const set = new Set(chars);
        let start = 0;
        let end = this.length;
        while (start < end && set.has(this[start])) {
            start++;
        }
        while (end > start && set.has(this[end - 1])) {
            end--;
        }
        return this.slice(start, end);
    },
    /**
     * @this {string}
     * @param {...any} args
     */
    startswith(...args) {
        const { prefix, start, end } = bindArgs(args, ["prefix", "start", "end"]);
        const prefixes = Array.isArray(prefix) ? prefix : [prefix];
        if (!prefixes.every((p) => typeof p === "string")) {
            throw new EvaluationError(
                "startswith first arg must be str or a tuple of str",
            );
        }
        const str = this.slice(start ?? 0, end ?? this.length);
        return prefixes.some((p) => str.startsWith(p));
    },
    /**
     * @this {string}
     * @param {...any} args
     */
    endswith(...args) {
        const { suffix, start, end } = bindArgs(args, ["suffix", "start", "end"]);
        const suffixes = Array.isArray(suffix) ? suffix : [suffix];
        if (!suffixes.every((s) => typeof s === "string")) {
            throw new EvaluationError(
                "endswith first arg must be str or a tuple of str",
            );
        }
        const str = this.slice(start ?? 0, end ?? this.length);
        return suffixes.some((s) => str.endsWith(s));
    },
    /**
     * @this {string}
     * @param {...any} args
     */
    replace(...args) {
        const params = bindArgs(args, ["old", "new", "count"]);
        const oldStr = params.old;
        const newStr = params.new;
        const count = params.count;
        if (typeof oldStr !== "string" || typeof newStr !== "string") {
            throw new EvaluationError("replace() arguments must be str");
        }
        if (count === undefined || count === null || count < 0) {
            return this.replaceAll(oldStr, newStr);
        }
        let rest = String(this);
        let out = "";
        for (let k = 0; k < count; k++) {
            const idx = rest.indexOf(oldStr);
            if (idx === -1) {
                break;
            }
            out += rest.slice(0, idx) + newStr;
            rest = rest.slice(idx + oldStr.length);
            if (oldStr === "") {
                // Empty pattern matches between every char; advance one char
                // per replacement, as Python does.
                if (!rest) {
                    break;
                }
                out += rest[0];
                rest = rest.slice(1);
            }
        }
        return out + rest;
    },
    /**
     * @this {string}
     * @param {...any} args
     */
    split(...args) {
        const { sep, maxsplit } = bindArgs(args, ["sep", "maxsplit"]);
        const max =
            maxsplit === undefined || maxsplit === null || maxsplit < 0
                ? Infinity
                : Math.trunc(maxsplit);
        const str = String(this);
        if (sep === undefined || sep === null) {
            // Python split(): split on whitespace runs, dropping empty parts.
            const result = [];
            let rest = str.replace(/^\s+/, "");
            while (rest && result.length < max) {
                const m = rest.match(/\s+/);
                if (!m) {
                    break;
                }
                result.push(rest.slice(0, m.index));
                rest = rest.slice(/** @type {number} */ (m.index) + m[0].length);
            }
            if (rest) {
                result.push(rest);
            }
            return result;
        }
        if (typeof sep !== "string") {
            throw new EvaluationError("must be str or None");
        }
        if (sep === "") {
            throw new EvaluationError("empty separator");
        }
        const parts = str.split(sep);
        if (parts.length - 1 <= max) {
            return parts;
        }
        // Python keeps the un-split remainder; JS's split limit drops it.
        return [...parts.slice(0, max), parts.slice(max).join(sep)];
    },
    /**
     * @this {string}
     * @param {...any} args
     */
    join(...args) {
        const { iterable } = bindArgs(args, ["iterable"]);
        return execOnIterable(iterable, (/** @type {Iterable<any>} */ it) => {
            const items = [...it];
            for (const item of items) {
                if (typeof item !== "string") {
                    throw new EvaluationError(
                        `sequence item: expected str instance, ${pyTypeName(item)} found`,
                    );
                }
            }
            return items.join(String(this));
        });
    },
    /**
     * Subset of str.format(): auto ({}), positional ({0}) and named ({name})
     * fields plus {{ }} escapes. Format specs / conversions ({x:>8}, {x!r})
     * and attribute/index access ({x.y}, {x[0]}) raise instead of rendering
     * wrong output.
     * @this {string}
     * @param {...any} args
     */
    format(...args) {
        const kwargs = args.at(-1) ?? {};
        const positional = args.slice(0, -1);
        let auto = 0;
        return this.replace(/\{\{|\}\}|\{([^{}]*)\}/g, (m, field) => {
            if (m === "{{") {
                return "{";
            }
            if (m === "}}") {
                return "}";
            }
            if (/[:!.[]/.test(field)) {
                throw new EvaluationError(
                    `str.format: unsupported replacement field '${field}'`,
                );
            }
            if (field === "" || /^\d+$/.test(field)) {
                const index = field === "" ? auto++ : Number(field);
                if (index >= positional.length) {
                    throw new EvaluationError(
                        `Replacement index ${index} out of range for positional args tuple`,
                    );
                }
                return pyStr(positional[index]);
            }
            if (!Object.hasOwn(kwargs, field)) {
                throw new EvaluationError(`KeyError: '${field}'`);
            }
            return pyStr(kwargs[field]);
        });
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
 * Bitwise/shift operators are integer-only in Python: floats raise TypeError
 * (JS would silently truncate) and non-numbers raise instead of coercing.
 * Booleans are ints, as everywhere else.
 *
 * @param {string} op operator symbol, for the error message
 * @param {any} left
 * @param {any} right
 */
function assertIntegerOperands(op, left, right) {
    const isInt = (/** @type {any} */ v) =>
        typeof v === "boolean" || (typeof v === "number" && Number.isInteger(v));
    if (!isInt(left) || !isInt(right)) {
        throw new EvaluationError(
            `unsupported operand type(s) for ${op}: '${pyTypeName(left)}' and '${pyTypeName(right)}'`,
        );
    }
}

/**
 * Python-style exponential notation: like toExponential but with the
 * exponent padded to at least two digits (``1.5e+2`` → ``1.500000e+02``).
 *
 * @param {number} num
 * @param {number} precision
 * @returns {string}
 */
function formatExponential(num, precision) {
    return num.toExponential(precision).replace(/e([+-])(\d)$/, "e$10$2");
}

/**
 * Python ``%g`` conversion: ``precision`` significant digits (0 counts as 1);
 * fixed notation when the decimal exponent is in [-4, precision), scientific
 * otherwise; trailing zeros stripped in both cases.
 *
 * @param {number} num
 * @param {number} precision
 * @returns {string}
 */
function formatGeneral(num, precision) {
    if (!Number.isFinite(num)) {
        return String(num);
    }
    const p = precision === 0 ? 1 : precision;
    if (num === 0) {
        return "0";
    }
    const eStr = num.toExponential(p - 1);
    const exp = Number(eStr.slice(eStr.indexOf("e") + 1));
    if (exp >= -4 && exp < p) {
        let str = num.toFixed(Math.max(0, p - 1 - exp));
        if (str.includes(".")) {
            str = str.replace(/\.?0+$/, "");
        }
        return str;
    }
    let [mantissa, exponent] = eStr.split("e");
    if (mantissa.includes(".")) {
        mantissa = mantissa.replace(/\.?0+$/, "");
    }
    return `${mantissa}e${exponent}`.replace(/e([+-])(\d)$/, "e$10$2");
}

/**
 * printf-style ``%`` formatting for strings (``'%s' % val`` /
 * ``'%s=%d' % (a, b)``). Supports the conversions that show up in real Odoo
 * expressions: s, r, d/i, f, e/g, x/X, o and the ``%%`` literal, with optional
 * flags / width / precision.
 *
 * Known limitation: py_js evaluates Python tuples AND lists to JS arrays, so
 * ``'%s' % [1, 2]`` is indistinguishable from ``'%s' % (1, 2)`` at runtime and
 * is spread as an argument tuple (→ "1", or "not enough arguments"), where
 * Python renders the list itself (→ "[1, 2]").
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
                if (
                    value === null ||
                    typeof value !== "object" ||
                    Array.isArray(value)
                ) {
                    throw new EvaluationError("format requires a mapping");
                }
                if (!Object.hasOwn(value, mapKey)) {
                    throw new EvaluationError(`KeyError: '${mapKey}'`);
                }
                arg = value[mapKey];
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
                    str = Number(arg).toFixed(prec != null ? Number(prec) : 6);
                    break;
                case "e":
                case "E": {
                    str = formatExponential(
                        Number(arg),
                        prec != null ? Number(prec) : 6,
                    );
                    if (conv === "E") {
                        str = str.toUpperCase();
                    }
                    break;
                }
                case "g":
                case "G": {
                    str = formatGeneral(Number(arg), prec != null ? Number(prec) : 6);
                    if (conv === "G") {
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
                if (flags.includes("-")) {
                    str = str.padEnd(w);
                } else if (flags.includes("0") && conv !== "s" && conv !== "r") {
                    // Python zero-pads AFTER the sign ('%05d' % -3 → "-0003")
                    // and ignores the 0 flag for string conversions.
                    const sign = str[0] === "-" || str[0] === "+" ? str[0] : "";
                    str = sign + str.slice(sign.length).padStart(w - sign.length, "0");
                } else {
                    str = str.padStart(w);
                }
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
                if (timeDeltaOnLeft && timeDeltaOnRight) {
                    // Python: timedelta * timedelta is a TypeError (only
                    // timedelta * number is defined). Reject instead of feeding
                    // a timedelta into multiply() as the scalar factor.
                    throw new EvaluationError(
                        "unsupported operand type(s) for *: 'timedelta' and 'timedelta'",
                    );
                }
                const number = timeDeltaOnLeft ? right : left;
                const delta = timeDeltaOnLeft ? left : right;
                // A non-numeric factor (e.g. td * "x") must raise, not coerce
                // to NaN inside multiply().
                assertNumericOperand("*", number);
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
        // KNOWN LIMITATION (Python 3 divergence): integer arithmetic (``+``,
        // ``-``, ``*``, ``**``) is done with JS doubles, which are exact only up
        // to 2**53. Python 3 ints are arbitrary precision, so large results lose
        // accuracy silently — ``2 ** 60`` → 1152921504606847000 (Python:
        // ...6976), ``999999999999 * 999999999999`` → a float. Note the
        // inconsistency with the bitwise ops below (``|``/``&``/``<<``/…), which
        // already do the maths in BigInt and RAISE on overflow. A proper fix
        // carries integer operands as BigInt through arithmetic too — deferred
        // because the result type would change (Number → BigInt) and every
        // downstream consumer (JSON, comparisons, field values) expects Number;
        // that is a focused, cross-cutting change. Rarely hit in domains/context.
        case "**": {
            assertNumericOperands("**", left, right);
            if (Number(left) === 0 && Number(right) < 0) {
                // Python: 0 ** negative → ZeroDivisionError (JS yields
                // Infinity), matching the guards on / // %.
                throw new EvaluationError(
                    "ZeroDivisionError: 0.0 cannot be raised to a negative power",
                );
            }
            const power = left ** right;
            if (!Number.isNaN(left) && !Number.isNaN(right) && Number.isNaN(power)) {
                // Negative base with a non-integer exponent → a complex number
                // in Python, which this evaluator does not model; JS yields NaN.
                // Raise instead of letting NaN flow silently through the rest of
                // the expression (the guard only fires when the NaN is produced
                // by ** itself, not when an operand was already NaN).
                throw new EvaluationError(
                    "negative number cannot be raised to a fractional power",
                );
            }
            return power;
        }
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
        // KNOWN LIMITATION (Python 3 divergence): ``is``/``is not`` are
        // implemented as JS ``===``/``!==``. Python's ``is`` tests object
        // identity with small-int interning, so ``1 is 1.0`` is False (int vs
        // float) and ``1000 is 1000`` is not guaranteed True — here both return
        // true. The common real-world uses (``x is None``, ``x is False``,
        // ``x is True``) are correct; only numeric identity is wrong, and that
        // essentially never appears in domains/modifiers. Not fixed because JS
        // cannot replicate CPython interning and there is no practical payoff.
        case "is":
            return left === null ? right === null : left === right;
        case "is not":
            return left === null ? right !== null : left !== right;
        case "|":
        case "^":
        case "&":
        case "<<":
        case ">>": {
            assertIntegerOperands(ast.op, left, right);
            // JS ``|`` ``^`` ``&`` ``<<`` ``>>`` coerce operands to 32-bit
            // signed ints, so ``1 << 40`` wrapped to 256 and ``4294967296 | 1``
            // truncated to 1 — silently wrong versus Python's arbitrary-precision
            // ints. Do the maths in BigInt, then narrow back, raising if the
            // exact result no longer fits a JS safe integer.
            const l = BigInt(left);
            const r = BigInt(right);
            if ((ast.op === "<<" || ast.op === ">>") && r < 0n) {
                throw new EvaluationError("negative shift count");
            }
            let result;
            switch (ast.op) {
                case "|":
                    result = l | r;
                    break;
                case "^":
                    result = l ^ r;
                    break;
                case "&":
                    result = l & r;
                    break;
                case "<<":
                    result = l << r;
                    break;
                default:
                    result = l >> r;
            }
            if (
                result > BigInt(Number.MAX_SAFE_INTEGER) ||
                result < BigInt(Number.MIN_SAFE_INTEGER)
            ) {
                throw new EvaluationError(
                    `integer result of '${ast.op}' exceeds the safe integer range`,
                );
            }
            return Number(result);
        }
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
                    // KNOWN LIMITATION (Python 3 divergence): a Python dict is a
                    // plain JS object, so numeric and string keys collide —
                    // ``{1: 'a'}[1]`` and ``{'1': 'a'}[1]`` both return 'a'
                    // (Python distinguishes int 1 from str '1'). Same root cause
                    // as the dict-membership note in py_compare.js:isIn; a proper
                    // fix backs dicts with a real ``Map``. Rare in practice
                    // (domains/context dicts are string-keyed).
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
                    } else if (
                        ast.key === "get" &&
                        typeof left === "object" &&
                        left !== null &&
                        !Array.isArray(left)
                    ) {
                        // dict-style .get on generic objects; lists have no
                        // .get in Python, so let them fall through and fail.
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
