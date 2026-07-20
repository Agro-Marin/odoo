// @ts-check
/** @odoo-module native */

/** @module @web/fields/parsers - Field value parsers for all ORM field types (date, float, integer, monetary, percentage, etc.) */

import { parseDate, parseDateTime } from "@web/core/l10n/dates";
import { localization } from "@web/core/l10n/localization";
import { evaluateExpr } from "@web/core/py_js/py";
import { registry } from "@web/core/registry";
import { escapeRegExp } from "@web/core/utils/format/strings";
// Helpers
/**
 * @param {string} expr
 * @param {object} [context]
 * @returns {any}
 */
import { Operation } from "@web/model/relational_model/operation";

/**
 * Memoizes a ``RegExp`` builder keyed on a string. Number parsing runs on every
 * keystroke of every numeric input, and the compiled regexes only depend on the
 * (rarely changing) localization separators — so caching by separator avoids
 * recompiling identical patterns on the hot path.
 *
 * @param {(key: string) => RegExp} build
 * @returns {(key: string) => RegExp}
 */
function memoizeRegex(build) {
    /** @type {Map<string, RegExp>} */
    const cache = new Map();
    return (key) => {
        let regex = cache.get(key);
        if (!regex) {
            regex = build(key);
            cache.set(key, regex);
        }
        return regex;
    };
}

const getOperationRegex = memoizeRegex(
    (decimalPoint) =>
        new RegExp(
            `^(?<operator>[+\\-*/])\\s*=\\s*(?<operand>-?\\d+(?:[${escapeRegExp(
                decimalPoint,
            )}]\\d+)?)$`,
        ),
);
const getThousandsSepRegex = memoizeRegex(
    (thousandsSep) => new RegExp(escapeRegExp(thousandsSep), "g"),
);
const getDecimalPointRegex = memoizeRegex(
    (decimalPoint) => new RegExp(escapeRegExp(decimalPoint), "g"),
);
const getMonetaryStartRegex = memoizeRegex(
    (decimalPoint) => new RegExp(`[\\d\\-+=]|${escapeRegExp(decimalPoint)}`),
);

// A whitespace thousands separator matches any run of whitespace, so it needs
// no per-separator compilation.
const WHITESPACE_THOUSANDS_SEP_REGEX = /\s+/g;

function evaluateMathematicalExpression(expr, context = {}) {
    const val = expr.replaceAll(" ", "");
    let safeEvalString = "";
    for (const part of val.split(/([-+*/()^])/g)) {
        /** @type {any} */
        let v = part;
        if (!["+", "-", "*", "/", "(", ")", "^"].includes(v) && v.length) {
            // check if this is a float and take into account user delimiter preference
            v = parseFloat(v);
        }
        if (v === "^") {
            v = "**";
        }
        safeEvalString += v;
    }
    return evaluateExpr(safeEvalString, context);
}

/**
 * @param {string} value
 * @param {(v: string) => any} parseValueFn
 * @returns {import("@web/model/relational_model/operation").Operation | false}
 */
function parseOperation(value, parseValueFn) {
    const match = value.match(getOperationRegex(localization.decimalPoint));
    if (match?.groups) {
        const operand = parseValueFn(match.groups.operand);
        const operator = match.groups.operator;
        return new Operation(/** @type {any} */ (operator), operand);
    }
    return false;
}

/**
 * Parses a string into a number.
 *
 * @param {string} value
 * @param {{ thousandsSep: string, decimalPoint: string }} [options]
 * @returns {number}
 */
function parseNumber(value, options = /** @type {any} */ ({})) {
    if (value.startsWith("=")) {
        // Return the un-truncated result: integer callers (parseInteger)
        // validate integrality themselves, so "=5/2" is rejected like "2.5"
        // instead of being silently floored to 2.
        return Number(evaluateMathematicalExpression(value.slice(1)));
    } else {
        // A whitespace thousands separator is equivalent to any whitespace character.
        // E.g. "1  000 000" should be parsed as 1000000 even if the
        // thousands separator is nbsp.
        const thousandsSepRegex = options.thousandsSep.match(/\s+/)
            ? WHITESPACE_THOUSANDS_SEP_REGEX
            : getThousandsSepRegex(options.thousandsSep);

        // a number can have the thousand separator multiple times. ex: 1,000,000.00
        value = value.replaceAll(thousandsSepRegex, "");
        // a number only have one decimal separator
        value = value.replace(getDecimalPointRegex(options.decimalPoint), ".");
    }

    return Number(value);
}

// Exports

class InvalidNumberError extends Error {}

/**
 * Try to extract a float from a string. The localization is considered in the process.
 *
 * @param {string} value
 * @param {{ allowOperation?: boolean }} [options]
 * @returns {number} a float
 */
export function parseFloat(value, { allowOperation = false } = {}) {
    if (typeof value === "string" && value.trim() === "") {
        return 0;
    }
    const operation = allowOperation ? parseOperation(value, parseFloat) : null;
    if (operation instanceof Operation) {
        // @ts-expect-error returns Operation when allowOperation is true
        return operation;
    }
    let parsed = parseNumber(value, {
        thousandsSep: localization.thousandsSep || "",
        decimalPoint: localization.decimalPoint,
    });
    if (Number.isNaN(parsed)) {
        parsed = parseNumber(value, {
            thousandsSep: ",",
            decimalPoint: ".",
        });
        if (Number.isNaN(parsed)) {
            throw new InvalidNumberError(`"${value}" is not a correct number`);
        }
    }
    if (!Number.isFinite(parsed)) {
        throw new InvalidNumberError(`"${value}" is not a valid number`);
    }
    return parsed;
}

/**
 * Try to extract a float time from a string. The localization is considered in the process.
 * The float time can have three formats: float, integer:integer, or
 * integer:integer:integer (hours:minutes:seconds). The seconds component lets
 * this round-trip the output of ``formatFloatTime`` when ``displaySeconds`` is
 * enabled (which emits ``HH:MM:SS``).
 *
 * @param {string} value
 * @returns {number} a float
 */
export function parseFloatTime(value) {
    let sign = 1;
    if (value[0] === "-") {
        value = value.slice(1);
        sign = -1;
    }
    const values = value.split(":");
    if (values.length > 3) {
        throw new InvalidNumberError(`"${value}" is not a correct number`);
    }
    if (values.length === 1) {
        return sign * parseFloat(value);
    }
    const hours = parseInteger(values[0]);
    const minutes = parseInteger(values[1]);
    if (minutes < 0 || minutes >= 60) {
        // The minutes component must be in [0, 59]; "1:90" is not 2.5 hours.
        throw new InvalidNumberError(`"${value}" is not a correct number`);
    }
    let seconds = 0;
    if (values.length === 3) {
        seconds = parseInteger(values[2]);
        if (seconds < 0 || seconds >= 60) {
            // The seconds component must be in [0, 59]; "1:00:90" is invalid.
            throw new InvalidNumberError(`"${value}" is not a correct number`);
        }
    }
    return sign * (hours + minutes / 60 + seconds / 3600);
}

/**
 * Try to extract an integer from a string. The localization is considered in the process.
 *
 * @param {string} value
 * @param {{ allowOperation?: boolean }} [options]
 * @returns {number} an integer
 */
export function parseInteger(value, { allowOperation = false } = {}) {
    if (typeof value === "string" && value.trim() === "") {
        return 0;
    }
    const operation = allowOperation ? parseOperation(value, parseInteger) : null;
    if (operation instanceof Operation) {
        // @ts-expect-error returns Operation when allowOperation is true
        return operation;
    }
    let parsed = parseNumber(value, {
        thousandsSep: localization.thousandsSep || "",
        decimalPoint: localization.decimalPoint,
    });
    // Only fall back to the English separators when the locale parse could not
    // interpret the input at all (NaN). Falling back on a valid-but-non-integer
    // result (e.g. "2,5" -> 2.5 in a comma-decimal locale) would silently
    // reinterpret "," as a thousands separator and yield 25 — a 10x error.
    // A finite non-integer is a genuine parse; reject it instead.
    if (Number.isNaN(parsed)) {
        parsed = parseNumber(value, {
            thousandsSep: ",",
            decimalPoint: ".",
        });
        if (Number.isNaN(parsed)) {
            throw new InvalidNumberError(`"${value}" is not a correct number`);
        }
    }
    if (!Number.isFinite(parsed)) {
        throw new InvalidNumberError(`"${value}" is not a valid number`);
    }
    if (!Number.isInteger(parsed)) {
        throw new InvalidNumberError(`"${value}" is not a correct number`);
    }
    if (parsed < -2147483648 || parsed > 2147483647) {
        throw new InvalidNumberError(
            `"${value}" is out of bounds (integers should be between -2,147,483,648 and 2,147,483,647)`,
        );
    }
    return parsed;
}

/**
 * Try to extract a float from a string and unconvert it with a conversion factor of 100.
 * The localization is considered in the process.
 * The percentage can have two formats: float or float%.
 *
 * When ``allowOperation`` is set and the input is a multi-edit operation
 * (``+= 5``, ``-= 5``, ...), the raw ``Operation`` is returned with its operand
 * **unscaled** — the caller (PercentageField.parse) rescales ``+=``/``-=``
 * operands by 1/100 since they apply to the displayed (×100) value.
 *
 * @param {string} value
 * @param {{ allowOperation?: boolean }} [options]
 * @returns {number | import("@web/model/relational_model/operation").Operation} float
 */
export function parsePercentage(value, { allowOperation = false } = {}) {
    if (value.at(-1) === "%") {
        value = value.slice(0, -1);
    }
    // parseFloat's declared return type omits the Operation it yields when
    // allowOperation is set, hence the widening cast.
    const parsed = /** @type {number | Operation} */ (
        parseFloat(value, { allowOperation })
    );
    if (parsed instanceof Operation) {
        return parsed;
    }
    return parsed / 100;
}

/**
 * Try to extract a monetary value from a string. The localization is considered in the process.
 * This function is lenient: it ignores everything before a substring starting with either
 * - a sign (- or +)
 * - an equals sign (signaling the start of a mathematical expression)
 * - a decimal point
 * - a number
 * Any non-numeric characters at the end are then removed.
 *
 * @param {string} value
 * @param {{ allowOperation?: boolean }} [options]
 * @returns {number}
 */
export function parseMonetary(value, { allowOperation = false } = {}) {
    const operation = allowOperation ? parseOperation(value, parseMonetary) : null;
    if (operation instanceof Operation) {
        // @ts-expect-error returns Operation when allowOperation is true
        return operation;
    }
    value = value.trim();
    const startRegex = getMonetaryStartRegex(localization.decimalPoint);
    const startMatch = value.match(startRegex);
    if (startMatch) {
        value = value.slice(startMatch.index);
    }
    // A prefix currency symbol sitting BETWEEN the sign and the digits (e.g.
    // "-$5.00") survives the slice above because the leading sign is the first
    // matched char. Re-locate the numeric start after the sign so the symbol is
    // dropped, otherwise Number("-$5.00") is NaN and the field is flagged
    // invalid (while "$-5.00" already parsed fine).
    if (value[0] === "-" || value[0] === "+") {
        const sign = value[0];
        const rest = value.slice(1);
        const restMatch = rest.match(startRegex);
        value = sign + (restMatch ? rest.slice(restMatch.index) : rest);
    }
    value = value.replace(/\D*$/, "");
    return parseFloat(value);
}

registry
    .category("parsers")
    .add("date", parseDate)
    .add("datetime", parseDateTime)
    .add("float", parseFloat)
    .add("float_time", parseFloatTime)
    .add("integer", parseInteger)
    .add("many2one_reference", parseInteger)
    .add("monetary", parseMonetary)
    .add("percentage", parsePercentage);

// Same contract as the ``formatters`` registry: every parser must be a
// callable. Predicate runs against existing entries and any third-party
// additions; throws in debug, warns in production. Field arch parsers
// (e.g. domain editor, search bar) invoke entries as
// ``parsers.get(type)(value)`` so non-function entries would surface
// downstream as ``TypeError: parser is not a function``; the predicate
// catches the bad registration earlier with a more specific message.
registry.category("parsers").addValidation((v) => typeof v === "function");
