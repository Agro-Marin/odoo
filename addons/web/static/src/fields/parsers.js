// @ts-check
/** @odoo-module native */

/** @module @web/fields/parsers - Field value parsers for all ORM field types (date, float, integer, monetary, percentage, etc.) */

import { parseDate, parseDateTime } from "@web/core/l10n/dates";
import { localization } from "@web/core/l10n/localization";
import { evaluateExpr } from "@web/core/py_js/py";
import { registry } from "@web/core/registry";
import { escapeRegExp } from "@web/core/utils/format/strings";
import { ParseError } from "@web/fields/parse_error";
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

const WHITESPACE_THOUSANDS_SEP_REGEX = /\s+/g;

/**
 * A decimal number literal, as produced by ``parseNumber`` once the locale's
 * thousands separator has been removed and its decimal point normalised to
 * ".". Anything else is rejected instead of being handed to ``Number()``.
 *
 * ``Number()`` also accepts the other JS numeric literal syntaxes, so without
 * this every parser silently read non-decimal input as a number:
 * ``"0x10" -> 16``, ``"0b11" -> 3``, ``"0o17" -> 15``. A user typing those into
 * a float field means none of them. Scientific notation IS kept — ``"1e5"`` is
 * a decimal literal people legitimately type.
 */
const DECIMAL_LITERAL_REGEX = /^[+-]?(\d+\.?\d*|\.\d+)([eE][+-]?\d+)?$/;

/**
 * Accounting notations for a negative amount, both of which the lenient
 * extraction in ``parseMonetary`` would otherwise discard along with the
 * currency decoration — silently turning -1,234.50 into +1,234.50:
 *
 * - parentheses, as used by IFRS/GAAP statements and spreadsheet exports;
 *   the capture groups keep any currency decoration around them so
 *   ``"USD (99)"`` still reaches the numeric extraction as ``"USD 99"``.
 * - a trailing minus, as emitted by SAP and mainframe exports.
 */
const PARENTHESISED_NEGATIVE_REGEX = /^(\D*)\((.*)\)(\D*)$/;
const TRAILING_MINUS_REGEX = /-\s*$/;

/**
 * Splits an ``=``-expression into operators and operand literals.
 *
 * A bare ``[-+*\/()^]`` class would also split the sign of an exponent, so
 * ``1e-5`` became ``["1e", "-", "5"]`` and the operand parse of ``"1e"``
 * failed — making ``=1e-5`` an error while ``=1e5`` parsed fine. The
 * lookbehind keeps a ``+``/``-`` attached when it directly follows the ``e``
 * of a numeric literal (``1e-5``, ``2E+3``) and splits it everywhere else
 * (``1-2``, ``1.5-2``).
 */
const EXPRESSION_TOKEN_REGEX = /([*/()^]|(?<![\d.,][eE])[-+])/;
const EXPRESSION_OPERATORS = ["+", "-", "*", "/", "(", ")", "^"];

function evaluateMathematicalExpression(expr, context = {}) {
    const val = expr.replaceAll(" ", "");
    let safeEvalString = "";
    for (const part of val.split(EXPRESSION_TOKEN_REGEX)) {
        /** @type {any} */
        let v = part;
        if (!EXPRESSION_OPERATORS.includes(v) && v.length) {
            // Operands are locale-formatted ("1.000,1"), so they go through
            // this module's locale-aware parseFloat — NOT the global one.
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
    // `Number()` — which this used to hand the raw string to — ignores leading
    // and trailing whitespace, and DECIMAL_LITERAL_REGEX does not. Without the
    // trim, a pasted " 10 " (spreadsheet copy, stray space) stopped being a
    // number and flagged the field invalid.
    value = value.trim();
    if (value.startsWith("=")) {
        try {
            return Number(evaluateMathematicalExpression(value.slice(1)));
        } catch (error) {
            if (error instanceof InvalidNumberError) {
                throw error;
            }
            // A malformed expression ("=(", "=1+*2") makes the python
            // evaluator raise its own error type. That is still rejected user
            // input, so it must surface as one — otherwise the input hook
            // would report it as a widget defect.
            throw new InvalidNumberError(`"${value}" is not a valid expression`, {
                cause: error,
            });
        }
    } else {
        const thousandsSepRegex = options.thousandsSep.match(/\s+/)
            ? WHITESPACE_THOUSANDS_SEP_REGEX
            : getThousandsSepRegex(options.thousandsSep);

        value = value.replaceAll(thousandsSepRegex, "");
        value = value.replace(getDecimalPointRegex(options.decimalPoint), ".");
        if (!DECIMAL_LITERAL_REGEX.test(value)) {
            return NaN;
        }
    }

    return Number(value);
}

/**
 * Rejected numeric user input. Exported so call sites can tell it apart from a
 * parser defect reaching the same ``catch`` (see {@link ParseError}).
 */
export class InvalidNumberError extends ParseError {}

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
    // Before the split: the sign is read positionally, so on " -1:30" it would
    // land inside the hours token instead, and `parseInteger` (which tolerates
    // its own padding) would then return -1 for the hours and +30 for the
    // minutes — yielding -0.5 for what the user wrote as -1.5.
    value = value.trim();
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
        throw new InvalidNumberError(`"${value}" is not a correct number`);
    }
    let seconds = 0;
    if (values.length === 3) {
        seconds = parseInteger(values[2]);
        if (seconds < 0 || seconds >= 60) {
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
    // Before the suffix test, which is positional: on "50% " the last
    // character is the space, the "%" survives into parseFloat and the whole
    // value is rejected.
    value = value.trim();
    if (value.at(-1) === "%") {
        value = value.slice(0, -1);
    }
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

    // Decide ONCE, after dropping any leading decoration, whether the input is
    // an ``=``-expression, and hand it to parseFloat whole if it is. Everything
    // from the ``=`` on is expression syntax, not currency decoration, and both
    // of the transformations below would corrupt it:
    //
    //  - the trailing ``\D*`` strip eats a closing parenthesis, so ``=(1+2)``
    //    reached parseFloat as ``=(1+2`` and was rejected as invalid input
    //    while ``=(1+2)*3`` (ending in a digit) parsed fine;
    //  - PARENTHESISED_NEGATIVE_REGEX reads the expression's own parentheses as
    //    the accounting negative notation, so a *decorated* expression like
    //    ``$ =(1+2)`` came out as -3.
    //
    // The old guard tested ``value.startsWith("=")`` before the decoration was
    // removed, so it covered the first case only for undecorated input and
    // never covered the second at all.
    const expressionMatch = value.match(startRegex);
    const body = expressionMatch ? value.slice(expressionMatch.index) : value;
    if (body.startsWith("=")) {
        return parseFloat(body);
    }

    // Recognise the negative notations before the lenient extraction below
    // strips them as if they were currency decoration.
    let sign = 1;
    const parenthesised = value.match(PARENTHESISED_NEGATIVE_REGEX);
    if (parenthesised) {
        sign = -sign;
        value = `${parenthesised[1]}${parenthesised[2]}${parenthesised[3]}`;
    }
    if (/\d/.test(value) && TRAILING_MINUS_REGEX.test(value)) {
        sign = -sign;
        value = value.replace(TRAILING_MINUS_REGEX, "");
    }

    const startMatch = value.match(startRegex);
    if (startMatch) {
        value = value.slice(startMatch.index);
    }
    if (value[0] === "-" || value[0] === "+") {
        const leadingSign = value[0];
        const rest = value.slice(1);
        const restMatch = rest.match(startRegex);
        value = leadingSign + (restMatch ? rest.slice(restMatch.index) : rest);
    }
    value = value.replace(/\D*$/, "");
    return sign * parseFloat(value);
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

registry.category("parsers").addValidation((v) => typeof v === "function");
