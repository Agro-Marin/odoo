// @ts-check
/** @odoo-module native */

/** @module @web/core/py_js/py_builtin - Python built-in functions (bool, len, set, sorted, etc.) for the JS evaluator */

// Runtime-only use inside max()/min(); the import cycle with py_compare.js
// (which needs pyTypeName/EvaluationError from here) is safe because neither
// side touches the other's bindings at module-evaluation time.
import { isLess } from "./py_compare.js";
import { PyDate, PyDateTime, PyRelativeDelta, PyTime, PyTimeDelta } from "./py_date.js";

export class EvaluationError extends Error {}

/**
 * Python ``repr()`` of a string: pick single quotes unless the string contains
 * a ``'`` and no ``"`` (then use double quotes), and escape the backslash, the
 * chosen quote and the common control characters. The old ``'${value}'`` gave
 * unparseable output for strings containing a quote or backslash
 * (``repr("it's")`` → ``'it's'``).
 *
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
 * Python ``repr()``: the unambiguous representation. Strings get quotes, lists
 * render as ``[1, 2]``, dicts as ``{'a': 1}``, sets as ``{1, 2}`` / ``set()``.
 * Typed Py* objects (PyDate, PyTimeDelta, ...) defer to their own toString.
 *
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
        // A typed Py* object defines its own toString; a plain dict is a
        // regular Object (see the defineProperty rework in py_parser /
        // py_interpreter) and only inherits Object.prototype.toString.
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
 * Python ``str()``: containers render like ``repr`` (``str([1, 2])`` → "[1, 2]"),
 * top-level strings stay unquoted, and typed Py* objects use their toString.
 *
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
    if (Array.isArray(value) || value instanceof Set) {
        return pyRepr(value);
    }
    if (typeof value === "object") {
        // Plain dicts render via repr; typed Py* objects (custom toString) do
        // not. Dict literals are regular Objects (see py_interpreter /
        // py_parser), so inheriting Object.prototype.toString (or having
        // none, for null-proto objects from other sources) means plain dict.
        return typeof value.toString !== "function" ||
            value.toString === Object.prototype.toString
            ? pyRepr(value)
            : value.toString();
    }
    return String(value);
}

/**
 * Python-compatible round() with half-to-even (banker's rounding).
 *
 * Unlike a naive multiply→round→divide approach, this examines the IEEE-754
 * decimal representation of the original value. This matches CPython's dtoa-based
 * round(), which operates on the stored double — not the decimal literal.
 *
 * Example: 2.675 is stored as 2.6749999999999998 (below halfway) → rounds to 2.67,
 * while 0.45 is stored as 0.45000000000000001 (above halfway) → rounds to 0.5.
 *
 * @param {number} value
 * @param {number} ndigits
 * @returns {number}
 */
export function _pythonRound(value, ndigits) {
    if (!Number.isFinite(value) || value === 0) {
        return value;
    }
    if (ndigits < 0) {
        // Negative ndigits: round to nearest 10^|ndigits|.
        // Integer powers of 10 are exact, so divide→round→multiply is safe.
        const factor = 10 ** -ndigits;
        return _pythonRound(value / factor, 0) * factor;
    }

    const sign = Math.sign(value);
    const abs = Math.abs(value);

    // 17 significant digits uniquely identify any IEEE-754 double, matching
    // CPython's dtoa shortest-representation behaviour.
    const repr = abs.toPrecision(17);
    if (repr.includes("e")) {
        // Extreme magnitudes (>10^17 or <10^-17): sub-ulp precision is
        // irrelevant, fall back to simple multiply approach.
        const factor = 10 ** ndigits;
        return Math.round(value * factor) / factor;
    }

    const dotIdx = repr.indexOf(".");
    const intPart = dotIdx === -1 ? repr : repr.slice(0, dotIdx);
    const decPart = dotIdx === -1 ? "" : repr.slice(dotIdx + 1);

    if (ndigits >= decPart.length) {
        return value; // fewer stored digits than requested precision
    }

    const roundDigit = Number.parseInt(decPart[ndigits]);
    const truncStr =
        ndigits === 0 ? intPart : `${intPart}.${decPart.slice(0, ndigits)}`;
    const truncated = Number.parseFloat(truncStr);
    const increment = 10 ** -ndigits;

    if (roundDigit < 5) {
        return sign * truncated;
    }
    if (roundDigit > 5) {
        return sign * (truncated + increment);
    }

    // roundDigit === 5: check remaining digits to determine if above/below/at halfway.
    const remaining = decPart.slice(ndigits + 1);
    if (/[1-9]/.test(remaining)) {
        // Digits after the '5' push the value above the halfway point → round away from zero.
        return sign * (truncated + increment);
    }

    // Exactly at halfway — banker's round (round to nearest even).
    const lastKeptDigit =
        ndigits === 0
            ? Number.parseInt(intPart[intPart.length - 1])
            : Number.parseInt(decPart[ndigits - 1]);
    if (lastKeptDigit % 2 === 0) {
        return sign * truncated;
    }
    return sign * (truncated + increment);
}

/**
 * Parse a Python ``int(str, base)`` literal. Mirrors CPython: an optional
 * ``+``/``-`` sign, base-matching ``0x``/``0o``/``0b`` prefixes, surrounding
 * whitespace, and single underscores between digits (and directly after the
 * base prefix — PEP 515). ``base === 0`` auto-detects from the prefix and
 * otherwise means decimal (rejecting redundant leading zeros, e.g.
 * ``int("010", 0)``). Throws the CPython ``invalid literal for int() with
 * base N`` message on malformed input.
 *
 * @param {string} raw
 * @param {number} base 0 or 2..36
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
            // A leading zero is legal only for the literal 0 (``int("010", 0)``
            // is a ValueError, but ``int("0", 0)`` / ``int("0_0", 0)`` are 0).
            if (/^0[0-9_]*[1-9]/.test(s)) {
                fail();
            }
        }
    } else if (prefixBase === base) {
        s = s.slice(2);
        hadPrefix = true;
    }
    // A single underscore may follow the base prefix (``0x_1f``); strip it so
    // the between-digits underscore rule below applies to the remainder.
    if (hadPrefix && s[0] === "_") {
        s = s.slice(1);
    }
    // Underscores are allowed only singly, between digits — never leading,
    // trailing, or doubled.
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
 * Python-ish type name for error messages.
 * @param {any} value
 * @returns {string}
 */
export function pyTypeName(value) {
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
 * @param {any} iterable
 * @param {Function} func
 */
export function execOnIterable(iterable, func) {
    if (iterable === null) {
        // new Set(null) is fine in js but set(None) (-> new Set(null))
        // is not in Python
        throw new EvaluationError(`value not iterable`);
    }
    if (
        typeof iterable === "object" &&
        !Array.isArray(iterable) &&
        !(iterable instanceof Set)
    ) {
        // dicts are considered as iterable in Python
        iterable = Object.keys(iterable);
    }
    if (typeof iterable?.[Symbol.iterator] !== "function") {
        // rules out undefined and other values not iterable
        throw new EvaluationError(`value not iterable`);
    }
    return func(iterable);
}

/**
 * Resolve the items for a Python-style ``max``/``min`` call: either a single
 * iterable argument or several positional ones. The trailing element is the
 * kwargs object the interpreter appends, so it is always dropped.
 *
 * The single-argument form accepts any Python iterable: arrays and Sets
 * spread into their elements, strings into their characters (``max("abc")``
 * is ``"c"``) and plain dicts iterate over their keys — all matching CPython.
 * A non-iterable single argument raises, as in Python.
 *
 * @param {any[]} args raw call arguments (kwargs object last)
 * @param {"max" | "min"} name for the empty-sequence error message
 * @returns {any[]}
 */
function maxMinItems(args, name) {
    const kwargs = args[args.length - 1];
    // `key=`/`default=` change WHICH element is returned; silently dropping
    // them (as slicing off kwargs did) returns a different value than the
    // server would. Fail loudly instead — matching this subsystem's
    // convention of raising on unsupported features.
    if (kwargs && typeof kwargs === "object" && Object.keys(kwargs).length) {
        throw new EvaluationError(
            `${name}() keyword arguments (${Object.keys(kwargs).join(", ")}) are not supported`,
        );
    }
    const values = args.slice(0, -1); // remove kwargs
    let items = values;
    if (values.length === 1) {
        const arg = values[0];
        if (typeof arg === "string") {
            items = arg.split("");
        } else if (arg !== null && typeof arg?.[Symbol.iterator] === "function") {
            items = [...arg];
        } else if (arg !== null && typeof arg === "object") {
            // dicts iterate over their keys in Python
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

export const BUILTINS = {
    /**
     * @param {any} value
     * @returns {boolean}
     */
    bool(value) {
        // The evaluator always appends a trailing kwargs object, so >1
        // positional means arguments.length > 2. CPython: bool() takes at
        // most 1 argument (mirrors the set() guard below).
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
                // typeof guard: a plain data dict may carry an `isTrue` KEY
                // (server-controlled json/properties values); only call it
                // when it is actually a method (same precedent as the
                // `isEqual` guard in py_interpreter.js).
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
            // we always receive at least one argument: kwargs (return fnValue(...args, kwargs); in FunctionCall case)
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
        // Share the interpreter's `isLess` kernel rather than the JS `>`:
        // `>` coerces with Number() (so max("b","a")/max(dateA,dateB) gave NaN)
        // AND stringifies lists (so max([[2],[10]]) wrongly returned [2] where
        // Python returns [10]). Keeping `acc` on ties matches Python's "first
        // maximal element wins".
        return items.reduce((acc, item) => (isLess(acc, item) ? item : acc));
    },

    min(/** @type {any[]} */ ...args) {
        const items = maxMinItems(args, "min");
        return items.reduce((acc, item) => (isLess(item, acc) ? item : acc));
    },

    time: {
        strftime(/** @type {string} */ format) {
            return PyDateTime.now().strftime(format);
        },
    },

    /** Return the length of a collection (array, string, Set, or object keys). */
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
        if (value && typeof value === "object") {
            return Object.keys(value).length;
        }
        throw new EvaluationError(`object of type '${typeof value}' has no len()`);
    },

    /** Return the absolute value of a number or timedelta. */
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
            // PyTimeDelta: negate if total duration is negative
            return value.total_seconds() >= 0 ? value : value.negate();
        }
        return Math.abs(value);
    },

    /**
     * Convert to integer. With no ``base`` it truncates a number toward zero
     * or parses a base-10 string; with an explicit ``base`` (2..36 or 0 for
     * prefix auto-detect) it parses a string in that base — ``int("ff", 16)``,
     * ``int("10", 2)``. The interpreter appends its trailing kwargs object, so
     * ``int(x)`` → rest=[{}], ``int(s, 2)`` → rest=[2, {}], ``int(s, base=2)``
     * → rest=[{base: 2}] (mirrors ``round``).
     */
    int(/** @type {any} */ value, /** @type {any[]} */ ...rest) {
        const kwargs = rest.at(-1);
        const base = rest.length > 1 ? rest[0] : kwargs?.base;
        if (base !== undefined) {
            // Python: int(number, base) raises "can't convert non-string with
            // explicit base"; the base itself must be 0 or 2..36.
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
            // Python: int(None)/int([]) raise TypeError; Number() would
            // silently coerce them to 0.
            throw new EvaluationError(
                `int() argument must be a string, a bytes-like object or a real number, not '${pyTypeName(value)}'`,
            );
        }
        return Math.trunc(value);
    },

    /** Convert to float. */
    float(/** @type {any} */ value) {
        if (typeof value === "boolean") {
            return value ? 1.0 : 0.0;
        }
        if (typeof value !== "number" && typeof value !== "string") {
            // Python: float(None)/float([]) raise TypeError; Number() would
            // silently coerce null to 0.
            throw new EvaluationError(
                `float() argument must be a string or a real number, not '${pyTypeName(value)}'`,
            );
        }
        if (typeof value === "string" && !value.trim()) {
            throw new EvaluationError(`could not convert string to float: '${value}'`);
        }
        if (typeof value === "string") {
            // CPython accepts "inf"/"infinity"/"nan" (case-insensitive, optional
            // sign); ``Number()`` only understands "Infinity", so float("inf")
            // was wrongly raising while float("Infinity") worked.
            const trimmed = value.trim();
            const magnitude = trimmed.replace(/^[+-]/, "").toLowerCase();
            if (magnitude === "inf" || magnitude === "infinity") {
                return trimmed[0] === "-" ? -Infinity : Infinity;
            }
            if (magnitude === "nan") {
                return NaN;
            }
        }
        const n = Number(value);
        if (Number.isNaN(n)) {
            throw new EvaluationError(`could not convert string to float: '${value}'`);
        }
        return n;
    },

    /** Convert to string. */
    str(/** @type {any} */ value) {
        // Known divergence: JS numbers carry no int/float distinction, so
        // str(1.0) returns "1" where Python returns "1.0".
        return pyStr(value);
    },

    /** Round a number to a given number of decimal places (banker's rounding). */
    round(/** @type {any} */ value, /** @type {any[]} */ ...rest) {
        // The interpreter always appends the kwargs object as the last
        // argument, so `round(x, ndigits=2)` arrives as rest = [{ndigits: 2}]
        // while `round(x, 2)` arrives as rest = [2, {}].
        const kwargs = rest.at(-1);
        const ndigits = rest.length > 1 ? rest[0] : (kwargs?.ndigits ?? 0);
        return _pythonRound(value, ndigits);
    },

    context_today() {
        // Alias of PyDate.today() (both the user-timezone date). Kept routed
        // through PyDate.today so a single date source stays mockable.
        return PyDate.today();
    },

    get current_date() {
        // deprecated: today should be preferred
        return this.today;
    },

    get today() {
        return PyDate.today().strftime("%Y-%m-%d");
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
