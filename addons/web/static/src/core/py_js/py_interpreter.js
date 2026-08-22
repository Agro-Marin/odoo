// @ts-check
/** @odoo-module native */

import { ASTType } from "./ast_type.js";
import { bindArgs } from "./py_args.js";
import {
    _pythonRound,
    BUILTINS,
    EvaluationError,
    execOnIterable,
    pyRepr,
    pyStr,
    pyTypeName,
} from "./py_builtin.js";
import { isEqual, isIn, isLess } from "./py_compare.js";
import { PyDate, PyDateTime, PyRelativeDelta, PyTime, PyTimeDelta } from "./py_date.js";
import { isPyTuple, markPyTuple } from "./py_tuple.js";
import { isPyDict, isPyMapping, toPyDict } from "./py_utils.js";

export { isPyTuple };

/**
 * @typedef {import("./ast_type.js").AST} AST
 */

const isTrue = BUILTINS.bool;

const BLOCKED_PROPERTIES = new Set([
    "constructor",
    "__proto__",
    "prototype",
    "__defineGetter__",
    "__defineSetter__",
    "__lookupGetter__",
    "__lookupSetter__",
]);

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
        const { key, defValue } = bindArgs(args, ["key", "defValue"], "get");
        if (Object.hasOwn(this, key)) {
            return this[key];
        } else if (defValue !== undefined) {
            return defValue;
        }
        return null;
    },
};

const STRING = {
    /**
     * @this {string}
     * @param {...any} args
     */
    lower(...args) {
        bindArgs(args, [], "lower");
        return this.toLowerCase();
    },
    /**
     * @this {string}
     * @param {...any} args
     */
    upper(...args) {
        bindArgs(args, [], "upper");
        return this.toUpperCase();
    },
    /**
     * @this {string}
     * @param {...any} args
     */
    capitalize(...args) {
        bindArgs(args, [], "capitalize");
        return this.charAt(0).toUpperCase() + this.slice(1).toLowerCase();
    },
    /**
     * @this {string}
     * @param {...any} args
     */
    title(...args) {
        bindArgs(args, [], "title");
        return this.replace(
            /\p{Alphabetic}[\p{Alphabetic}\p{Mn}]*/gu,
            (word) => word[0].toUpperCase() + word.slice(1).toLowerCase(),
        );
    },
    /**
     * @this {string}
     * @param {...any} args
     */
    strip(...args) {
        const { chars } = bindArgs(args, ["chars"], "strip");
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
        const { prefix, start, end } = bindArgs(
            args,
            ["prefix", "start", "end"],
            "startswith",
        );
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
        const { suffix, start, end } = bindArgs(
            args,
            ["suffix", "start", "end"],
            "endswith",
        );
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
        const params = bindArgs(args, ["old", "new", "count"], "replace");
        const oldStr = params.old;
        const newStr = params.new;
        const count = params.count;
        if (typeof oldStr !== "string" || typeof newStr !== "string") {
            throw new EvaluationError("replace() arguments must be str");
        }
        if (count === undefined || count === null) {
            return this.replaceAll(oldStr, newStr);
        }
        if (!Number.isInteger(count) && typeof count !== "boolean") {
            throw new EvaluationError(
                `replace() count must be an integer, not '${pyTypeName(count)}'`,
            );
        }
        if (count < 0) {
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
        const { sep, maxsplit } = bindArgs(args, ["sep", "maxsplit"], "split");
        const max =
            maxsplit === undefined || maxsplit === null || maxsplit < 0
                ? Infinity
                : Math.trunc(maxsplit);
        const str = String(this);
        if (sep === undefined || sep === null) {
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
        return [...parts.slice(0, max), parts.slice(max).join(sep)];
    },
    /**
     * @this {string}
     * @param {...any} args
     */
    join(...args) {
        const { iterable } = bindArgs(args, ["iterable"], "join");
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
     * @this {string}
     * @param {...any} args
     */
    format(...args) {
        const kwargs = args.at(-1) ?? {};
        const positional = args.slice(0, -1);
        let auto = 0;
        /** @type {"auto" | "manual" | null} */
        let mode = null;
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
                const isAuto = field === "";
                if (mode === null) {
                    mode = isAuto ? "auto" : "manual";
                } else if ((mode === "auto") !== isAuto) {
                    throw new EvaluationError(
                        isAuto
                            ? "cannot switch from manual field specification to automatic field numbering"
                            : "cannot switch from automatic field numbering to manual field specification",
                    );
                }
                const index = isAuto ? auto++ : Number(field);
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
 * @param {import("./ast_type.js").ASTUnaryOperator} ast
 * @param {(ast: AST) => any} recurse
 * @returns {any}
 */
function _applyUnaryOp(ast, recurse) {
    const value = recurse(ast.right);
    switch (ast.op) {
        case "-":
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
        case "~": {
            const isInt =
                typeof value === "boolean" ||
                (typeof value === "number" && Number.isInteger(value));
            if (!isInt) {
                throw new EvaluationError(
                    `bad operand type for unary ~: '${pyTypeName(value)}'`,
                );
            }
            const result = ~BigInt(value);
            if (
                result > BigInt(Number.MAX_SAFE_INTEGER) ||
                result < BigInt(Number.MIN_SAFE_INTEGER)
            ) {
                throw new EvaluationError(
                    "integer result of '~' exceeds the safe integer range",
                );
            }
            return Number(result);
        }
    }
    throw new EvaluationError(`Unknown unary operator: ${ast.op}`);
}

/**
 * @param {string} op
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
 * @param {string} op
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
 * @param {string} op
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
 * @param {number} a
 * @param {number} b
 * @returns {number}
 */
function pyFloorDiv(a, b) {
    const mod = a % b;
    let div = (a - mod) / b;
    if (mod !== 0 && b < 0 !== mod < 0) {
        div -= 1;
    }
    const floordiv = Math.floor(div);
    const result = div - floordiv > 0.5 ? floordiv + 1 : floordiv;
    return result === 0 ? 0 : result;
}

/**
 * @param {number} a
 * @param {number} b
 * @returns {number}
 */
function pyMod(a, b) {
    const mod = a % b;
    return mod !== 0 && mod < 0 !== b < 0 ? mod + b : mod;
}

/**
 * @param {number} num
 * @param {number} precision
 * @returns {[string, number]}
 */
function roundedMantissa(num, precision) {
    const [rawMantissa, rawExponent] = num.toExponential(20).split("e");
    let exponent = Number(rawExponent);
    const negative = rawMantissa.startsWith("-");
    const digits = rawMantissa.replace("-", "").replace(".", "");
    let kept = digits.slice(0, precision + 1);
    const rest = digits.slice(precision + 1);
    let roundUp = rest[0] > "5";
    if (rest[0] === "5") {
        roundUp =
            /[1-9]/.test(rest.slice(1)) || Number(kept[kept.length - 1]) % 2 === 1;
    }
    if (roundUp) {
        const incremented = kept.split("");
        let carry = 1;
        for (let i = incremented.length - 1; i >= 0 && carry; i--) {
            const digit = Number(incremented[i]) + carry;
            incremented[i] = String(digit % 10);
            carry = digit < 10 ? 0 : 1;
        }
        kept = incremented.join("");
        if (carry) {
            kept = `1${kept.slice(0, -1)}`;
            exponent += 1;
        }
    }
    const mantissa = precision > 0 ? `${kept[0]}.${kept.slice(1)}` : kept[0];
    return [negative ? `-${mantissa}` : mantissa, exponent];
}

/**
 * @param {number} exponent
 * @returns {string}
 */
function formatExponentSuffix(exponent) {
    const sign = exponent < 0 ? "-" : "+";
    return `e${sign}${String(Math.abs(exponent)).padStart(2, "0")}`;
}

/**
 * @param {number} num
 * @param {number} precision
 * @param {boolean} [alt]
 * @returns {string}
 */
function formatExponential(num, precision, alt = false) {
    if (!Number.isFinite(num)) {
        return num.toExponential(precision);
    }
    let [mantissa, exponent] = roundedMantissa(num, precision);
    if (alt && !mantissa.includes(".")) {
        mantissa += ".";
    }
    return mantissa + formatExponentSuffix(exponent);
}

/**
 * @param {number} num
 * @param {number} precision
 * @returns {string}
 */
function formatFixed(num, precision) {
    if (!Number.isFinite(num)) {
        return num.toFixed(precision);
    }
    return _pythonRound(num, precision).toFixed(precision);
}

/**
 * @param {number} num
 * @param {number} precision
 * @param {boolean} [alt]
 * @returns {string}
 */
function formatGeneral(num, precision, alt = false) {
    if (!Number.isFinite(num)) {
        return String(num);
    }
    const p = precision === 0 ? 1 : precision;
    if (num === 0) {
        return alt ? `0.${"0".repeat(p - 1)}` : "0";
    }
    let [mantissa, exponent] = roundedMantissa(num, p - 1);
    if (exponent >= -4 && exponent < p) {
        const str = formatFixed(num, Math.max(0, p - 1 - exponent));
        if (!alt) {
            return str.includes(".") ? str.replace(/\.?0+$/, "") : str;
        }
        return str.includes(".") ? str : `${str}.`;
    }
    if (!alt && mantissa.includes(".")) {
        mantissa = mantissa.replace(/\.?0+$/, "");
    } else if (alt && !mantissa.includes(".")) {
        mantissa += ".";
    }
    return mantissa + formatExponentSuffix(exponent);
}

/**
 * @param {string} fmt
 * @param {any} value
 * @returns {string}
 */
function pyStringFormat(fmt, value) {
    const values = isPyTuple(value) ? value.slice() : [value];
    const isMapping = isPyMapping(value);
    let i = 0;
    const formatted = fmt.replace(
        /%(?:\((\w+)\))?([-+ #0]*)(\d+)?(?:\.(\d+))?([a-zA-Z%])/g,
        (m, mapKey, flags, width, prec, conv) => {
            if (conv === "%") {
                return "%";
            }
            let arg;
            if (mapKey != null) {
                if (!isMapping) {
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
            if (
                conv !== "s" &&
                conv !== "r" &&
                conv !== "c" &&
                !"diufFeEgGxXo".includes(conv)
            ) {
                throw new EvaluationError(
                    `ValueError: unsupported format character '${conv}' (0x${conv
                        .charCodeAt(0)
                        .toString(16)})`,
                );
            }
            const precision = prec != null ? Number(prec) : null;
            const w = width ? Number(width) : 0;
            const leftAlign = flags.includes("-");

            if (conv === "c") {
                let str;
                if (typeof arg === "boolean" || Number.isInteger(arg)) {
                    const code = Number(arg);
                    if (code < 0 || code > 0x10ffff) {
                        throw new EvaluationError(
                            "OverflowError: %c arg not in range(0x110000)",
                        );
                    }
                    str = String.fromCodePoint(code);
                } else if (typeof arg === "string" && [...arg].length === 1) {
                    str = arg;
                } else if (typeof arg === "string") {
                    throw new EvaluationError(
                        `TypeError: %c requires an int or a unicode character, not a string of length ${[...arg].length}`,
                    );
                } else {
                    throw new EvaluationError(
                        `TypeError: %c requires an int or a unicode character, not ${pyTypeName(arg)}`,
                    );
                }
                if (w > str.length) {
                    str = leftAlign ? str.padEnd(w) : str.padStart(w);
                }
                return str;
            }

            if (conv === "s" || conv === "r") {
                let str = conv === "s" ? pyStr(arg) : pyRepr(arg);
                if (precision != null) {
                    str = str.slice(0, precision);
                }
                if (w > str.length) {
                    str = leftAlign ? str.padEnd(w) : str.padStart(w);
                }
                return str;
            }

            if (typeof arg !== "number" && typeof arg !== "boolean") {
                throw new EvaluationError(
                    `TypeError: %${conv} format: a number is required, not '${pyTypeName(arg)}'`,
                );
            }
            const num = Number(arg);
            const sign =
                num < 0
                    ? "-"
                    : flags.includes("+")
                      ? "+"
                      : flags.includes(" ")
                        ? " "
                        : "";
            let prefix = "";
            let body;
            const zeroPad = flags.includes("0");
            const alt = flags.includes("#");
            const isIntConv = "diuxXo".includes(conv);
            if (!Number.isFinite(num) && "diu".includes(conv)) {
                throw new EvaluationError(
                    Number.isNaN(num)
                        ? "ValueError: cannot convert float NaN to integer"
                        : "OverflowError: cannot convert float infinity to integer",
                );
            }
            if (isIntConv) {
                if (
                    "xXo".includes(conv) &&
                    typeof arg !== "boolean" &&
                    !Number.isInteger(num)
                ) {
                    throw new EvaluationError(
                        `TypeError: %${conv} format: an integer is required, not ${pyTypeName(arg)}`,
                    );
                }
                const base = conv === "o" ? 8 : conv === "x" || conv === "X" ? 16 : 10;
                body = Math.trunc(Math.abs(num)).toString(base);
                if (conv === "X") {
                    body = body.toUpperCase();
                }
                if (precision != null) {
                    body = body.padStart(precision, "0");
                }
                if (alt) {
                    prefix =
                        conv === "o"
                            ? "0o"
                            : conv === "x"
                              ? "0x"
                              : conv === "X"
                                ? "0X"
                                : "";
                }
            } else if (!Number.isFinite(num)) {
                body = Number.isNaN(num) ? "nan" : "inf";
                if (conv === "F" || conv === "E" || conv === "G") {
                    body = body.toUpperCase();
                }
            } else {
                const magnitude = Math.abs(num);
                const p = precision != null ? precision : 6;
                if (conv === "f" || conv === "F") {
                    body = formatFixed(magnitude, p);
                    if (alt && !body.includes(".")) {
                        body += ".";
                    }
                } else if (conv === "e" || conv === "E") {
                    body = formatExponential(magnitude, p, alt);
                    if (conv === "E") {
                        body = body.toUpperCase();
                    }
                } else {
                    body = formatGeneral(magnitude, p, alt);
                    if (conv === "G") {
                        body = body.toUpperCase();
                    }
                }
            }

            let str = sign + prefix + body;
            if (w > str.length) {
                if (leftAlign) {
                    str = str.padEnd(w);
                } else if (zeroPad) {
                    const head = sign + prefix;
                    str = head + body.padStart(w - head.length, "0");
                } else {
                    str = str.padStart(w);
                }
            }
            return str;
        },
    );
    if (!isMapping && i < values.length) {
        throw new EvaluationError(
            "not all arguments converted during string formatting",
        );
    }
    return formatted;
}

/**
 * @type {Record<string, (left: any, right: any) => boolean>}
 */
const COMPARISONS = {
    "==": (left, right) => isEqual(left, right),
    "<>": (left, right) => !isEqual(left, right),
    "!=": (left, right) => !isEqual(left, right),
    "<": (left, right) => isLess(left, right),
    ">": (left, right) => isLess(right, left),
    ">=": (left, right) => isEqual(left, right) || isLess(right, left),
    "<=": (left, right) => isEqual(left, right) || isLess(left, right),
    in: (left, right) => isIn(left, right),
    "not in": (left, right) => !isIn(left, right),
    is: (left, right) => (left === null ? right === null : left === right),
    "is not": (left, right) => (left === null ? right !== null : left !== right),
};

/**
 * @param {import("./ast_type.js").ASTBinaryOperator} ast
 * @param {(ast: AST) => any} recurse
 * @returns {any}
 */
function _applyBinaryOp(ast, recurse) {
    const left = recurse(ast.left);
    const right = recurse(ast.right);
    if (Object.hasOwn(COMPARISONS, ast.op)) {
        return COMPARISONS[ast.op](left, right);
    }
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
            if (timeDeltaOnLeft || timeDeltaOnRight) {
                const date = timeDeltaOnLeft ? right : left;
                const delta = timeDeltaOnLeft ? left : right;
                if (!(date instanceof PyDate) && !(date instanceof PyDateTime)) {
                    throw new EvaluationError(
                        `unsupported operand type(s) for +: '${pyTypeName(left)}' and '${pyTypeName(right)}'`,
                    );
                }
                return date.add(delta);
            }
            if (Array.isArray(left) && Array.isArray(right)) {
                return [...left, ...right];
            }
            if (typeof left === "string" && typeof right === "string") {
                return left + right;
            }
            const leftNumeric = typeof left === "number" || typeof left === "boolean";
            const rightNumeric =
                typeof right === "number" || typeof right === "boolean";
            if (leftNumeric && rightNumeric) {
                return /** @type {number} */ (left) + /** @type {number} */ (right);
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
                if (
                    left instanceof PyTimeDelta ||
                    left instanceof PyDate ||
                    left instanceof PyDateTime
                ) {
                    return left.subtract(right);
                }
                throw new EvaluationError(
                    `unsupported operand type(s) for -: '${pyTypeName(left)}' and '${pyTypeName(right)}'`,
                );
            }

            if (left instanceof PyDateTime) {
                if (!(right instanceof PyDateTime)) {
                    throw new EvaluationError(
                        `unsupported operand type(s) for -: '${pyTypeName(left)}' and '${pyTypeName(right)}'`,
                    );
                }
                return left.subtract(right);
            }
            if (left instanceof PyDate) {
                if (!(right instanceof PyDate)) {
                    throw new EvaluationError(
                        `unsupported operand type(s) for -: '${pyTypeName(left)}' and '${pyTypeName(right)}'`,
                    );
                }
                return left.subtract(right);
            }
            if (left instanceof Set && right instanceof Set) {
                return left.difference(right);
            }
            assertNumericOperands("-", left, right);
            return left - right;
        }
        case "*": {
            const timeDeltaOnLeft = left instanceof PyTimeDelta;
            const timeDeltaOnRight = right instanceof PyTimeDelta;
            if (timeDeltaOnLeft || timeDeltaOnRight) {
                if (timeDeltaOnLeft && timeDeltaOnRight) {
                    throw new EvaluationError(
                        "unsupported operand type(s) for *: 'timedelta' and 'timedelta'",
                    );
                }
                const number = timeDeltaOnLeft ? right : left;
                const delta = timeDeltaOnLeft ? left : right;
                assertNumericOperand("*", number);
                return delta.multiply(number);
            }

            const leftSeq = typeof left === "string" || Array.isArray(left);
            const rightSeq = typeof right === "string" || Array.isArray(right);
            if (leftSeq !== rightSeq) {
                const seq = leftSeq ? left : right;
                const count = leftSeq ? right : left;
                if (!Number.isInteger(count) && typeof count !== "boolean") {
                    throw new EvaluationError(
                        `can't multiply sequence by non-int of type '${pyTypeName(count)}'`,
                    );
                }
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
                return left.divideTrue(Number(right));
            }
            assertNumericOperands("/", left, right);
            if (Number(right) === 0) {
                throw new EvaluationError("ZeroDivisionError: division by zero");
            }
            return left / right;
        case "%": {
            if (typeof left === "string") {
                return pyStringFormat(left, right);
            }
            if (left instanceof PyTimeDelta && right instanceof PyTimeDelta) {
                const rus = right.toMicroseconds();
                if (rus === 0) {
                    throw new EvaluationError("ZeroDivisionError: modulo by zero");
                }
                const lus = left.toMicroseconds();
                return PyTimeDelta.create({ microseconds: pyMod(lus, rus) });
            }
            assertNumericOperands("%", left, right);
            if (Number(right) === 0) {
                throw new EvaluationError("ZeroDivisionError: modulo by zero");
            }
            return pyMod(Number(left), Number(right));
        }
        case "//":
            if (left instanceof PyTimeDelta) {
                if (right instanceof PyTimeDelta) {
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
            return pyFloorDiv(Number(left), Number(right));
        case "**": {
            assertNumericOperands("**", left, right);
            if (Number(left) === 0 && Number(right) < 0) {
                throw new EvaluationError(
                    "ZeroDivisionError: 0.0 cannot be raised to a negative power",
                );
            }
            const power = left ** right;
            if (!Number.isNaN(left) && !Number.isNaN(right) && Number.isNaN(power)) {
                throw new EvaluationError(
                    "negative number cannot be raised to a fractional power",
                );
            }
            return power;
        }
        case "|":
        case "^":
        case "&":
        case "<<":
        case ">>": {
            if (left instanceof Set && right instanceof Set) {
                switch (ast.op) {
                    case "|":
                        return left.union(right);
                    case "&":
                        return left.intersection(right);
                    case "^":
                        return left.symmetricDifference(right);
                    default:
                        throw new EvaluationError(
                            `unsupported operand type(s) for ${ast.op}: 'set' and 'set'`,
                        );
                }
            }
            assertIntegerOperands(ast.op, left, right);
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

/**
 * @param {any} _class
 * @returns {any[]}
 */
function methods(_class) {
    return Object.getOwnPropertyNames(_class.prototype)
        .filter((prop) => prop !== "constructor")
        .map((prop) => _class.prototype[prop]);
}

/**
 * @type {Set<any>}
 */
const allowedFns = new Set([
    PyDate,
    PyDateTime,
    PyTime,
    PyTimeDelta,
    PyRelativeDelta,

    BUILTINS.time.strftime,
    BUILTINS.set,
    BUILTINS.bool,
    BUILTINS.min,
    BUILTINS.max,
    BUILTINS.len,
    BUILTINS.abs,
    BUILTINS.sorted,
    BUILTINS.repr,
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

/**
 * @param {any} value
 * @returns {boolean}
 */
function isPyValue(value) {
    return (
        typeof value === "number" ||
        typeof value === "boolean" ||
        Array.isArray(value) ||
        value instanceof PyDate ||
        value instanceof PyDateTime ||
        value instanceof PyTime ||
        value instanceof PyTimeDelta ||
        value instanceof PyRelativeDelta
    );
}

/**
 * @param {object} table
 * @param {string} typeName
 * @param {string} key
 * @returns {any}
 */
function attributeOf(table, typeName, key) {
    if (!Object.hasOwn(table, key)) {
        throw new EvaluationError(
            `AttributeError: '${typeName}' object has no attribute '${key}'`,
        );
    }
    return /** @type {Record<string, any>} */ (table)[key];
}

const unboundFn = Symbol("unbound function");

/**
 * @param {AST} ast
 * @param {Record<string, any>} context
 * @returns {any}
 */
export function evaluate(ast, context = {}) {
    const dicts = new Set();
    /** @type {any} */
    let pyContext;
    let evalDepth = 0;
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
                    } else if (Object.hasOwn(BUILTINS, name)) {
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
                case ASTType.Chain: {
                    let left = _evaluate(ast.operands[0]);
                    for (const [index, op] of ast.operators.entries()) {
                        if (!Object.hasOwn(COMPARISONS, op)) {
                            throw new EvaluationError(
                                `Unknown comparison operator: ${op}`,
                            );
                        }
                        const right = _evaluate(ast.operands[index + 1]);
                        if (!COMPARISONS[op](left, right)) {
                            return false;
                        }
                        left = right;
                    }
                    return true;
                }
                case ASTType.BooleanOperator: {
                    const left = _evaluate(ast.left);
                    if (ast.op === "and") {
                        return isTrue(left) ? _evaluate(ast.right) : left;
                    } else {
                        return isTrue(left) ? left : _evaluate(ast.right);
                    }
                }
                case ASTType.List:
                    return ast.value.map(_evaluate);
                case ASTType.Tuple:
                    return markPyTuple(ast.value.map(_evaluate));
                case ASTType.Dictionary: {
                    /** @type {Record<string, any>} */
                    const dict = {};
                    for (const key of Object.keys(ast.value || {})) {
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
                    if (typeof dict === "string" || Array.isArray(dict)) {
                        if (typeof key !== "number" || !Number.isInteger(key)) {
                            throw new EvaluationError(
                                `${Array.isArray(dict) ? "list" : "string"} indices must be integers, not '${pyTypeName(key)}'`,
                            );
                        }
                        const value = key < 0 ? dict.at(key) : dict[key];
                        if (value === undefined) {
                            throw new EvaluationError(
                                `IndexError: ${Array.isArray(dict) ? "list" : "string"} index out of range`,
                            );
                        }
                        return value;
                    }
                    if (isPyMapping(dict) && !Object.hasOwn(dict, key)) {
                        throw new EvaluationError(`KeyError: ${pyRepr(key)}`);
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
                    if (left === null || left === undefined) {
                        throw new EvaluationError(
                            `AttributeError: 'NoneType' object has no attribute '${ast.key}'`,
                        );
                    }
                    if (dicts.has(left) || isPyDict(left)) {
                        result = attributeOf(DICT, "dict", ast.key);
                    } else if (typeof left === "string") {
                        result = attributeOf(STRING, "str", ast.key);
                    } else if (left instanceof Set) {
                        result = attributeOf(SET, "set", ast.key);
                    } else if (
                        ast.key === "get" &&
                        typeof left === "object" &&
                        left !== null &&
                        !Array.isArray(left)
                    ) {
                        result = /** @type {Record<string, any>} */ (DICT)[ast.key];
                        left = toPyDict(left);
                    } else {
                        if (BLOCKED_PROPERTIES.has(ast.key)) {
                            throw new EvaluationError(
                                `Access to '${ast.key}' is forbidden`,
                            );
                        }
                        if (isPyValue(left) && !(ast.key in Object(left))) {
                            throw new EvaluationError(
                                `AttributeError: '${pyTypeName(left)}' object has no attribute '${ast.key}'`,
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
            throw new EvaluationError("Invalid Function Call");
        }
        return val;
    }
    return _evaluate(ast);
}
