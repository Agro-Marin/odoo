// @ts-check
/** @odoo-module native */

/** @module @web/core/py_js/py_builtin */

import { isLess } from "./py_compare.js";
import { PyDate, PyDateTime, PyRelativeDelta, PyTime, PyTimeDelta } from "./py_date.js";
import { EvaluationError } from "./py_errors.js";
import { pyTypeName } from "./py_type_name.js";
import { isPyMapping } from "./py_utils.js";

export { EvaluationError } from "./py_errors.js";
export { pyTypeName } from "./py_type_name.js";

/**
 * @param {string} s
 * @returns {string}
 */
function pyReprString(s) {
    const quote = s.includes("'") && !s.includes('"') ? '"' : "'";
    let out = quote;
    for (const ch of s) {
        if (ch === "\\" || ch === quote) {
            out += "\\" + ch;
        } else if (ch === "\n") {
            out += "\\n";
        } else if (ch === "\r") {
            out += "\\r";
        } else if (ch === "\t") {
            out += "\\t";
        } else {
            out += ch;
        }
    }
    return out + quote;
}

/**
 * A number the way Python spells it, as far as one JS number type allows.
 *
 * Two things JS spells differently and that are *not* the int/float problem:
 *
 * - non-finite values, which printed as ``Infinity`` / ``NaN`` -- JavaScript
 *   spellings that no Python ever produces, and that flowed into domains and
 *   ``%s`` output verbatim;
 * - the exponent threshold. Python switches to scientific below ``1e-4``,
 *   JS only below ``1e-6``, and JS writes a one-digit exponent (``1e-7``)
 *   where Python pads to two (``1e-07``).
 *
 * Only the SMALL side is corrected. Above ``1e16`` Python also switches to
 * scientific, but every float that large is integral, so it is indistinguishable
 * from an int here -- and ``str(10000000000000000)`` really is
 * ``'10000000000000000'``. That one belongs to the int/float unification this
 * module cannot close; a value below ``1e-4`` is never an integer, so it does.
 *
 * @param {number} value
 * @returns {string}
 */
function pyNumberStr(value) {
    if (Number.isNaN(value)) {
        return "nan";
    }
    if (value === Infinity) {
        return "inf";
    }
    if (value === -Infinity) {
        return "-inf";
    }
    if (value !== 0 && Math.abs(value) < 1e-4) {
        // `toExponential()` with no argument keeps the shortest round-tripping
        // mantissa, which is what Python's repr uses too.
        return value.toExponential().replace(/e([+-])(\d)$/, "e$10$2");
    }
    return String(value);
}

/**
 * @param {any} value
 * @returns {string}
 */
export function pyRepr(value) {
    if (value === null || value === undefined) {
        return "None";
    }
    if (typeof value === "boolean") {
        return value ? "True" : "False";
    }
    if (typeof value === "number") {
        return pyNumberStr(value);
    }
    if (typeof value === "string") {
        return pyReprString(value);
    }
    if (Array.isArray(value)) {
        return `[${value.map(pyRepr).join(", ")}]`;
    }
    if (value instanceof Set) {
        return value.size === 0 ? "set()" : `{${[...value].map(pyRepr).join(", ")}}`;
    }
    if (typeof value === "object") {
        if (
            typeof value.toString === "function" &&
            value.toString !== Object.prototype.toString
        ) {
            return value.toString();
        }
        const entries = Object.keys(value).map(
            (k) => `${pyRepr(k)}: ${pyRepr(value[k])}`,
        );
        return `{${entries.join(", ")}}`;
    }
    return String(value);
}

/**
 * @param {any} value
 * @returns {string}
 */
export function pyStr(value) {
    if (value === null || value === undefined) {
        return "None";
    }
    if (typeof value === "boolean") {
        return value ? "True" : "False";
    }
    if (typeof value === "number") {
        return pyNumberStr(value);
    }
    if (Array.isArray(value) || value instanceof Set) {
        return pyRepr(value);
    }
    if (typeof value === "object") {
        return typeof value.toString !== "function" ||
            value.toString === Object.prototype.toString
            ? pyRepr(value)
            : value.toString();
    }
    return String(value);
}

/** Scratch view used to read a double's exact IEEE-754 fields. */
const F64_VIEW = new DataView(new ArrayBuffer(8));

/**
 * Decompose a finite, non-zero, positive double into `mantissa * 2 ** exponent`
 * with both parts integral. binary64 values are dyadic rationals, so this is
 * exact -- which is the whole point: every decimal *rendering* of a double is
 * already a rounding, and rounding a rounding is what this module got wrong.
 *
 * @param {number} value
 * @returns {{ mantissa: bigint, exponent: number }}
 */
function _decomposeDouble(value) {
    F64_VIEW.setFloat64(0, value);
    const hi = F64_VIEW.getUint32(0);
    const lo = F64_VIEW.getUint32(4);
    const biasedExponent = (hi >>> 20) & 0x7ff;
    const rawMantissa = (BigInt(hi & 0xfffff) << 32n) | BigInt(lo);
    if (biasedExponent === 0) {
        // Subnormal: no implicit leading bit.
        return { mantissa: rawMantissa, exponent: -1074 };
    }
    return { mantissa: rawMantissa | (1n << 52n), exponent: biasedExponent - 1075 };
}

/**
 * CPython's `round()` for floats, including its half-to-even tie-break.
 *
 * The tie-break has to be decided on the double's EXACT value, never on a
 * decimal rendering of it. The previous implementation tested
 * `abs.toPrecision(17)`, and 17 significant digits is precisely the width at
 * which a value that merely *approaches* a tie becomes indistinguishable from
 * one: 1.05 is exactly 1.05000000000000004440892098500626... so CPython rounds
 * it up, while `(1.05).toPrecision(17)` is "1.0500000000000000" -- an exact
 * tie, whose even last kept digit then rounded it *down*. Measured against
 * CPython 3.14 over 7,070 cases, 12.1% disagreed: 180 in direction and the
 * rest by one ulp, the latter because the result was rebuilt as
 * `truncated + increment` in binary (`round(0.0135, 3)` returned
 * 0.013999999999999999 rather than 0.014).
 *
 * So: do the comparison in exact integer arithmetic, and re-enter the float
 * domain through a decimal string, which `Number()` parses correctly-rounded
 * exactly as CPython's decimal->double conversion does.
 *
 * @param {number} value
 * @param {number} ndigits
 * @returns {number}
 */
export function _pythonRound(value, ndigits) {
    if (typeof ndigits === "boolean") {
        // `bool` is a subclass of `int` in Python, so `round(2.675, True)` is
        // `round(2.675, 1)` rather than an error.
        ndigits = ndigits ? 1 : 0;
    }
    if (!Number.isInteger(ndigits)) {
        throw new EvaluationError(
            `'${pyTypeName(ndigits)}' object cannot be interpreted as an integer`,
        );
    }
    if (!Number.isFinite(value) || value === 0) {
        return value;
    }
    // No double carries more than 1074 fractional bits, nor more than 309
    // integral digits, so outside this band the answer is already exact.
    if (ndigits > 1100) {
        return value;
    }
    if (ndigits < -400) {
        return value < 0 ? -0 : 0;
    }

    const negative = value < 0;
    const { mantissa, exponent } = _decomposeDouble(Math.abs(value));

    // |value| * 10**ndigits as an exact fraction num/den.
    let num = mantissa;
    let den = 1n;
    if (exponent >= 0) {
        num <<= BigInt(exponent);
    } else {
        den <<= BigInt(-exponent);
    }
    if (ndigits >= 0) {
        num *= 10n ** BigInt(ndigits);
    } else {
        den *= 10n ** BigInt(-ndigits);
    }

    let quotient = num / den;
    const doubledRemainder = (num % den) * 2n;
    if (doubledRemainder > den || (doubledRemainder === den && quotient % 2n === 1n)) {
        quotient += 1n;
    }

    let text;
    if (ndigits > 0) {
        const digits = quotient.toString().padStart(ndigits + 1, "0");
        text = `${digits.slice(0, -ndigits)}.${digits.slice(-ndigits)}`;
    } else if (ndigits === 0) {
        text = quotient.toString();
    } else {
        text = quotient.toString() + "0".repeat(-ndigits);
    }
    const result = Number(text);
    return negative ? -result : result;
}

/**
 * @param {string} raw
 * @param {number} base
 * @returns {number}
 */
function pyIntFromString(raw, base) {
    const fail = () => {
        throw new EvaluationError(
            `invalid literal for int() with base ${base}: ${pyRepr(raw)}`,
        );
    };
    let s = raw.trim();
    let negative = false;
    if (s[0] === "+" || s[0] === "-") {
        negative = s[0] === "-";
        s = s.slice(1);
    }
    const prefixBase = { "0x": 16, "0o": 8, "0b": 2 }[s.slice(0, 2).toLowerCase()];
    let hadPrefix = false;
    if (base === 0) {
        if (prefixBase) {
            base = prefixBase;
            s = s.slice(2);
            hadPrefix = true;
        } else {
            base = 10;
            if (/^0[0-9_]*[1-9]/.test(s)) {
                fail();
            }
        }
    } else if (prefixBase === base) {
        s = s.slice(2);
        hadPrefix = true;
    }
    if (hadPrefix && s[0] === "_") {
        s = s.slice(1);
    }
    if (!s || s[0] === "_" || s.at(-1) === "_" || s.includes("__")) {
        fail();
    }
    const digits = s.replace(/_/g, "");
    const alphabet = "0123456789abcdefghijklmnopqrstuvwxyz".slice(0, base);
    if (!new RegExp(`^[${alphabet}]+$`, "i").test(digits)) {
        fail();
    }
    const n = Number.parseInt(digits, base);
    return negative ? -n : n;
}

/**
 * @param {any} iterable
 * @param {Function} func
 */
export function execOnIterable(iterable, func) {
    if (iterable === null) {
        throw new EvaluationError(`value not iterable`);
    }
    if (
        typeof iterable === "object" &&
        !Array.isArray(iterable) &&
        !(iterable instanceof Set)
    ) {
        iterable = Object.keys(iterable);
    }
    if (typeof iterable?.[Symbol.iterator] !== "function") {
        throw new EvaluationError(`value not iterable`);
    }
    return func(iterable);
}

/**
 * @param {any[]} args
 * @param {"max" | "min"} name
 * @returns {any[]}
 */
function maxMinItems(args, name) {
    const kwargs = args[args.length - 1];
    if (kwargs && typeof kwargs === "object" && Object.keys(kwargs).length) {
        throw new EvaluationError(
            `${name}() keyword arguments (${Object.keys(kwargs).join(", ")}) are not supported`,
        );
    }
    const values = args.slice(0, -1);
    let items = values;
    if (values.length === 1) {
        const arg = values[0];
        if (typeof arg === "string") {
            items = arg.split("");
        } else if (arg !== null && typeof arg?.[Symbol.iterator] === "function") {
            items = [...arg];
        } else if (arg !== null && typeof arg === "object") {
            items = Object.keys(arg);
        } else {
            throw new EvaluationError(`'${pyTypeName(arg)}' object is not iterable`);
        }
    }
    if (items.length === 0) {
        throw new EvaluationError(`${name}() arg is an empty sequence`);
    }
    return items;
}

const PY_FLOAT_REGEXP = /^[+-]?(?:\d+\.?\d*|\.\d+)(?:e[+-]?\d+)?$/i;

export const BUILTINS = {
    /**
     * @param {any} value
     * @returns {boolean}
     */
    bool(value) {
        if (arguments.length > 2) {
            throw new EvaluationError(
                `bool expected at most 1 argument, got ${arguments.length - 1}`,
            );
        }
        if (value === undefined || value === null) {
            return false;
        }
        switch (typeof value) {
            case "number":
                return value !== 0;
            case "string":
                return value !== "";
            case "boolean":
                return value;
            case "object":
                if (typeof value.isTrue === "function") {
                    return value.isTrue();
                }
                if (Array.isArray(value)) {
                    return !!value.length;
                }
                if (value instanceof Set) {
                    return !!value.size;
                }
                return Object.keys(value).length !== 0;
        }
        return true;
    },

    set(/** @type {any} */ iterable) {
        if (arguments.length > 2) {
            throw new EvaluationError(
                `set expected at most 1 argument, got (${arguments.length - 1})`,
            );
        }
        return execOnIterable(
            iterable,
            (/** @type {any} */ iterable) => new Set(iterable),
        );
    },

    max(/** @type {any[]} */ ...args) {
        const items = maxMinItems(args, "max");
        return items.reduce((acc, item) => (isLess(acc, item) ? item : acc));
    },

    min(/** @type {any[]} */ ...args) {
        const items = maxMinItems(args, "min");
        return items.reduce((acc, item) => (isLess(item, acc) ? item : acc));
    },

    sorted(/** @type {any} */ iterable, /** @type {any[]} */ ...rest) {
        const kwargs = rest.at(-1) ?? {};
        const unsupported = Object.keys(kwargs).filter((key) => key !== "reverse");
        if (unsupported.length) {
            throw new EvaluationError(
                `sorted() keyword arguments (${unsupported.join(", ")}) are not supported`,
            );
        }
        const sign = BUILTINS.bool(kwargs.reverse) ? -1 : 1;
        return execOnIterable(iterable, (/** @type {Iterable<any>} */ it) =>
            [...it].sort((a, b) => sign * (isLess(a, b) ? -1 : isLess(b, a) ? 1 : 0)),
        );
    },

    repr(/** @type {any} */ value) {
        return pyRepr(value);
    },

    time: {
        strftime(/** @type {string} */ format) {
            return PyDateTime.now().strftime(format);
        },
    },

    len(/** @type {any} */ value) {
        if (arguments.length > 2) {
            throw new EvaluationError(
                `len() takes exactly one argument (${arguments.length - 1} given)`,
            );
        }
        if (typeof value === "string" || Array.isArray(value)) {
            return value.length;
        }
        if (value instanceof Set) {
            return value.size;
        }
        // Only a mapping, not "any object": counting own properties answered 3
        // for `len(datetime.date(2020, 1, 1))`, which CPython rejects.
        if (isPyMapping(value)) {
            return Object.keys(value).length;
        }
        throw new EvaluationError(`object of type '${pyTypeName(value)}' has no len()`);
    },

    abs(/** @type {any} */ value) {
        if (arguments.length > 2) {
            throw new EvaluationError(
                `abs() takes exactly one argument (${arguments.length - 1} given)`,
            );
        }
        if (
            value instanceof Object &&
            typeof value.negate === "function" &&
            typeof value.total_seconds === "function"
        ) {
            return value.total_seconds() >= 0 ? value : value.negate();
        }
        if (typeof value !== "number" && typeof value !== "boolean") {
            throw new EvaluationError(
                `bad operand type for abs(): '${pyTypeName(value)}'`,
            );
        }
        return Math.abs(Number(value));
    },

    int(/** @type {any} */ value, /** @type {any[]} */ ...rest) {
        const kwargs = rest.at(-1);
        const base = rest.length > 1 ? rest[0] : kwargs?.base;
        if (base !== undefined) {
            if (typeof value !== "string") {
                throw new EvaluationError(
                    "int() can't convert non-string with explicit base",
                );
            }
            if (typeof base !== "number" || !Number.isInteger(base)) {
                throw new EvaluationError("int() base must be an integer");
            }
            if (base !== 0 && (base < 2 || base > 36)) {
                throw new EvaluationError("int() base must be >= 2 and <= 36, or 0");
            }
            return pyIntFromString(value, base);
        }
        if (typeof value === "boolean") {
            return value ? 1 : 0;
        }
        if (typeof value === "string") {
            return pyIntFromString(value, 10);
        }
        if (typeof value !== "number") {
            throw new EvaluationError(
                `int() argument must be a string, a bytes-like object or a real number, not '${pyTypeName(value)}'`,
            );
        }
        return Math.trunc(value);
    },

    float(/** @type {any} */ value) {
        if (typeof value === "boolean") {
            return value ? 1.0 : 0.0;
        }
        if (typeof value === "number") {
            return value;
        }
        if (typeof value !== "string") {
            throw new EvaluationError(
                `float() argument must be a string or a real number, not '${pyTypeName(value)}'`,
            );
        }
        const invalid = () =>
            new EvaluationError(`could not convert string to float: '${value}'`);
        const trimmed = value.trim();
        if (!trimmed) {
            throw invalid();
        }
        const magnitude = trimmed.replace(/^[+-]/, "").toLowerCase();
        if (magnitude === "inf" || magnitude === "infinity") {
            return trimmed[0] === "-" ? -Infinity : Infinity;
        }
        if (magnitude === "nan") {
            return NaN;
        }
        const bare = trimmed.replace(/(?<=[0-9])_(?=[0-9])/g, "");
        if (!PY_FLOAT_REGEXP.test(bare)) {
            throw invalid();
        }
        return Number(bare);
    },

    str(/** @type {any} */ value) {
        return pyStr(value);
    },

    round(/** @type {any} */ value, /** @type {any[]} */ ...rest) {
        const kwargs = rest.at(-1);
        const ndigits = rest.length > 1 ? rest[0] : (kwargs?.ndigits ?? 0);
        if (typeof value === "boolean") {
            value = value ? 1 : 0;
        }
        if (typeof value !== "number") {
            throw new EvaluationError(
                `type ${pyTypeName(value)} doesn't define __round__ method`,
            );
        }
        return _pythonRound(value, ndigits);
    },

    context_today() {
        return PyDate.contextToday();
    },

    get current_date() {
        return this.today;
    },

    get today() {
        return PyDate.contextToday().strftime("%Y-%m-%d");
    },

    get now() {
        return PyDateTime.now().strftime("%Y-%m-%d %H:%M:%S");
    },

    datetime: {
        time: PyTime,
        timedelta: PyTimeDelta,
        datetime: PyDateTime,
        date: PyDate,
    },

    relativedelta: PyRelativeDelta,

    true: true,
    false: false,
};
