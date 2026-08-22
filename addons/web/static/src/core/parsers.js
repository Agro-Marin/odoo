// @ts-check
/** @odoo-module native */

import { parseDate, parseDateTime } from "@web/core/l10n/dates";
import { localization } from "@web/core/l10n/localization";
import { ParseError } from "@web/core/parse_error";
import { evaluateExpr } from "@web/core/py_js/py";
import { registry } from "@web/core/registry";
import { escapeRegExp } from "@web/core/utils/format/strings";
import { Operation } from "@web/core/utils/operation";

/**
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

const DECIMAL_LITERAL_REGEX = /^[+-]?(\d+\.?\d*|\.\d+)([eE][+-]?\d+)?$/;

const PARENTHESISED_NEGATIVE_REGEX = /^(\D*)\((.*)\)(\D*)$/;
const TRAILING_MINUS_REGEX = /-\s*$/;

const EXPRESSION_TOKEN_REGEX = /([*/()^]|(?<![\d.,][eE])[-+])/;
const EXPRESSION_OPERATORS = ["+", "-", "*", "/", "(", ")", "^"];

function evaluateMathematicalExpression(/** @type {string} */ expr) {
    const val = expr.replaceAll(" ", "");
    let safeEvalString = "";
    for (const part of val.split(EXPRESSION_TOKEN_REGEX)) {
        /** @type {any} */
        let v = part;
        if (!EXPRESSION_OPERATORS.includes(v) && v.length) {
            v = parseFloat(v);
        }
        if (v === "^") {
            v = "**";
        }
        safeEvalString += v;
    }
    return evaluateExpr(safeEvalString);
}

/**
 * @param {string} value
 * @param {(v: string) => any} parseValueFn
 * @returns {import("@web/core/utils/operation").Operation | false}
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
 * @param {string} value
 * @param {{ thousandsSep: string, decimalPoint: string }} options
 * @returns {number}
 */
function parseNumber(value, options) {
    value = value.trim();
    if (value.startsWith("=")) {
        try {
            return Number(evaluateMathematicalExpression(value.slice(1)));
        } catch (error) {
            if (error instanceof InvalidNumberError) {
                throw error;
            }
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

export class InvalidNumberError extends ParseError {}

/**
 * @param {string} value
 * @returns {number}
 * @throws {InvalidNumberError}
 */
function parseInLocale(value) {
    let parsed = parseNumber(value, {
        thousandsSep: localization.thousandsSep || "",
        decimalPoint: localization.decimalPoint,
    });
    if (Number.isNaN(parsed)) {
        parsed = parseNumber(value, { thousandsSep: ",", decimalPoint: "." });
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
 * @param {string} value
 * @param {{ allowOperation?: boolean }} [options]
 * @returns {number}
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
    return parseInLocale(value);
}

/**
 * @param {string} value
 * @returns {number}
 */
export function parseFloatTime(value) {
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
 * @param {string} value
 * @param {{ allowOperation?: boolean }} [options]
 * @returns {number}
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
    const parsed = parseInLocale(value);
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
 * @param {string} value
 * @param {{ allowOperation?: boolean }} [options]
 * @returns {number | import("@web/core/utils/operation").Operation}
 */
export function parsePercentage(value, { allowOperation = false } = {}) {
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

    const expressionMatch = value.match(startRegex);
    const body = expressionMatch ? value.slice(expressionMatch.index) : value;
    if (body.startsWith("=")) {
        return parseFloat(body);
    }

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
