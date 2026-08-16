// @ts-check
/** @odoo-module native */

/** @module @web/core/utils/format/numbers */

import { localization as l10n } from "@web/core/l10n/localization";
import { _t } from "@web/core/translation";
import { intersperse } from "@web/core/utils/format/strings";

/**
 * @param {number} num
 * @param {number} min
 * @param {number} max
 * @returns {number}
 */
export function clamp(num, min, max) {
    return Math.max(Math.min(num, max), min);
}

/**
 * @param {number} start
 * @param {number} stop
 * @param {number} step
 * @returns {number[]}
 */
export function range(start, stop, step = 1) {
    if (step === 0) {
        throw new Error("range() step argument must not be zero");
    }
    const array = [];
    const nsteps = Math.ceil((stop - start) / step);
    for (let i = 0; i < nsteps; i++) {
        array.push(start + step * i);
    }
    return array;
}

/**
 * Tie-break away from zero, like ``float_round``'s private ``round()``
 * (``odoo/libs/numbers/float_utils.py``). ``Math.round`` breaks ties toward
 * +Infinity instead, so it answers -2 for -2.5 where the server answers -3;
 * rounding the magnitude and reapplying the sign is what realigns them. The
 * first branch reproduces the server's ``round(f + 1) - round(f) != 1`` guard
 * for magnitudes where consecutive integers are no longer one ULP apart.
 *
 * @param {number} value
 * @returns {number}
 */
function roundHalfAwayFromZero(value) {
    const magnitude = Math.abs(value);
    if (Math.round(magnitude + 1) - Math.round(magnitude) !== 1) {
        return value + Math.sign(value) * 0.5;
    }
    return Math.round(magnitude) * Math.sign(value);
}

/**
 * Mirrors ``odoo.libs.numbers.float_utils.float_round``. The two must agree:
 * tax and Point of Sale compute the same amounts on both sides and compare
 * them (``base_tax/static/src/helpers/account_tax.js``), so any divergence
 * shows up as a client total that disagrees with the server's.
 *
 * @param {number} value
 * @param {number} precision
 * @param {"HALF-UP" | "HALF-DOWN" | "HALF-EVEN" | "UP" | "DOWN"} [method="HALF-UP"]
 */
export function roundPrecision(value, precision, method = "HALF-UP") {
    if (value === 0) {
        return 0;
    }
    if (typeof value !== "number" || !Number.isFinite(value)) {
        return NaN;
    }
    if (!precision || precision < 0) {
        precision = 1;
    }
    let roundingFactor = precision;
    let normalize = (/** @type {number} */ val) => val / roundingFactor;
    let denormalize = (/** @type {number} */ val) => val * roundingFactor;
    if (roundingFactor < 1) {
        roundingFactor = invertFloat(roundingFactor);
        [normalize, denormalize] = [denormalize, normalize];
    }
    const normalizedValue = normalize(value);
    if (normalizedValue === 0) {
        return 0;
    }
    const sign = Math.sign(normalizedValue);
    const epsilonMagnitude = Math.log2(Math.abs(normalizedValue));
    const epsilon = 2 ** (epsilonMagnitude - 50);
    const halfEpsilon = Math.max(0, Math.min(epsilon, 0.5 - epsilon / 2));
    // Past |normalizedValue| = 2^49 the raw epsilon exceeds 0.5 (and past 2^50
    // it exceeds 1, which would make `UP` nudge *downward*). The server clamps
    // it for the two truncating methods; `halfEpsilon` has its own clamp.
    const truncEpsilon = Math.min(epsilon, 0.5);
    let roundedValue;

    switch (method) {
        case "DOWN": {
            roundedValue = Math.trunc(normalizedValue + sign * truncEpsilon);
            break;
        }
        case "HALF-DOWN": {
            const integral = Math.floor(Math.abs(normalizedValue));
            const remainder = Math.abs(normalizedValue) - integral;
            // `halfEpsilon` collapses to 0 at |normalizedValue| >= 2^50, where
            // the strict inequality can no longer detect an exact tie.
            const isHalf = remainder === 0.5 || Math.abs(0.5 - remainder) < halfEpsilon;
            roundedValue = isHalf
                ? sign * integral
                : roundHalfAwayFromZero(normalizedValue - sign * halfEpsilon);
            break;
        }
        case "HALF-UP": {
            roundedValue = roundHalfAwayFromZero(normalizedValue + sign * halfEpsilon);
            break;
        }
        case "HALF-EVEN": {
            const integral = Math.floor(normalizedValue);
            const remainder = Math.abs(normalizedValue - integral);
            const isHalf = remainder === 0.5 || Math.abs(0.5 - remainder) < halfEpsilon;
            roundedValue = isHalf
                ? integral + (integral & 1)
                : roundHalfAwayFromZero(normalizedValue);
            break;
        }
        case "UP": {
            roundedValue = Math.trunc(normalizedValue + sign * (1 - truncEpsilon));
            break;
        }
        default: {
            throw new Error(`Unknown rounding method: ${method}`);
        }
    }

    return denormalize(roundedValue);
}

/**
 * @param {number} value
 * @param {number} decimals
 * @returns {string}
 */
function formatFixedDecimals(value, decimals) {
    if (Math.abs(value) >= 1e21) {
        return String(value);
    }
    const rounded = roundDecimals(value, decimals);
    return rounded.toFixed(decimals);
}

const NEGATIVE_POWERS_OF_TEN = Object.freeze([
    1, 1e-1, 1e-2, 1e-3, 1e-4, 1e-5, 1e-6, 1e-7, 1e-8, 1e-9, 1e-10, 1e-11, 1e-12, 1e-13,
    1e-14, 1e-15,
]);

/**
 * @param {number} value
 * @param {number} decimals
 * @returns {number}
 */
export function roundDecimals(value, decimals) {
    const precision = NEGATIVE_POWERS_OF_TEN[decimals] ?? parseFloat("1e" + -decimals);
    return roundPrecision(value, precision);
}

/**
 * @param {number} value
 * @param {number} decimals
 * @returns {boolean}
 */
export function floatIsZero(value, decimals) {
    return value === 0 || roundDecimals(value, decimals) === 0;
}

/**
 * @param {string} number
 * @param {string | false} [thousandsSep=","]
 * @param {number[]} [grouping=[]]
 * @returns {string}
 */
export function insertThousandsSep(number, thousandsSep = ",", grouping = []) {
    const negative = number[0] === "-";
    number = negative ? number.slice(1) : number;
    return (negative ? "-" : "") + intersperse(number, grouping, thousandsSep);
}

/**
 * ``minIntegerDigits`` is how many digits are kept before a unit suffix is
 * applied: at 3, 1500000 renders "1,500k" rather than "2M". It is deliberately
 * *not* called ``minDigits`` — that is ``formatFloat``'s minimum number of
 * *decimal* places, and the two used to share a name while ``formatFloat``
 * forwarded its whole option object here.
 *
 * @param {number} number
 * @param {Object} [options]
 * @param {number} [options.decimals=0]
 * @param {number} [options.minIntegerDigits=1]
 * @returns {string}
 */
export function humanNumber(number, options = {}) {
    const decimals = options.decimals || 0;
    const minIntegerDigits = options.minIntegerDigits || 1;
    const d2 = 10 ** decimals;
    const numberMagnitude = Number(number.toExponential().split("e")[1]);
    number = roundDecimals(number, decimals);
    if (numberMagnitude >= 21) {
        number = Math.round(number * 10 ** (decimals - numberMagnitude)) / d2;
        return `${number}e+${numberMagnitude}`;
    }
    const unitSymbols = _t("kMGTPE").toString();
    const sign = Math.sign(number);
    number = Math.abs(number);
    let symbol = "";
    for (let i = unitSymbols.length; i > 0; i--) {
        const s = 10 ** (i * 3);
        if (s <= number / 10 ** (minIntegerDigits - 1)) {
            number = Math.round((number * d2) / s) / d2;
            symbol = unitSymbols[i - 1];
            break;
        }
    }
    const { decimalPoint, grouping, thousandsSep } = l10n;

    const decimalsToKeep = number >= 1000 ? 0 : decimals;
    number = sign * number;
    const [integerPart, decimalPart] = formatFixedDecimals(
        number,
        decimalsToKeep,
    ).split(".");
    const int = insertThousandsSep(integerPart, thousandsSep, grouping);
    if (!decimalPart) {
        return int + symbol;
    }
    return int + decimalPoint + decimalPart + symbol;
}

/**
 * @param {number} value
 * @param {Object} [options]
 * @param {number[]} [options.digits]
 * @param {number} [options.minDigits] minimum number of decimal places
 * @param {number} [options.minIntegerDigits] humanReadable only, see humanNumber
 * @param {boolean} [options.humanReadable]
 * @param {string} [options.decimalPoint]
 * @param {string} [options.thousandsSep]
 * @param {number[]} [options.grouping]
 * @param {number} [options.decimals]
 * @param {boolean} [options.trailingZeros=true]
 * @returns {string}
 */
export function formatFloat(value, options = {}) {
    let precision;
    if (options.digits && options.digits[1] !== undefined) {
        precision = options.digits[1];
    } else if (options.minDigits) {
        const intDigitsCount =
            value !== 0 ? Math.floor(Math.log10(Math.abs(value))) + 1 : 1;
        const maxDecDigits = Math.max(15 - intDigitsCount, 0);
        precision = Math.min(6, maxDecDigits);
    } else {
        precision = 2;
    }
    // Clamped: `minDigits` is a floor on the decimals *shown*, never a licence
    // to show more than the value carries. Left unclamped it padded a value
    // already rounded to `precision`, so 12.5432 at digits=[16,2] minDigits=4
    // rendered "12.5400" -- two invented zeros in place of two real digits,
    // where the server's `ir.qweb.field.float` prints "12.54" (it applies
    // min_precision only `if min_precision < precision`).
    const minPrecision = Math.min(options.minDigits || precision, precision);
    if (floatIsZero(value, precision)) {
        value = 0.0;
    }
    if (options.humanReadable) {
        return humanNumber(value, options);
    }
    const grouping = options.grouping || l10n.grouping;
    const thousandsSep =
        "thousandsSep" in options ? options.thousandsSep : l10n.thousandsSep;
    const decimalPoint =
        "decimalPoint" in options ? options.decimalPoint : l10n.decimalPoint;
    const fixed = formatFixedDecimals(value, precision);
    if (fixed.includes("e")) {
        return fixed;
    }
    const formatted = fixed.split(".");
    formatted[0] = insertThousandsSep(formatted[0], thousandsSep, grouping);
    if (formatted[1]) {
        formatted[1] = formatted[1].replace(/0+$/, "");
        if (options.trailingZeros !== false) {
            formatted[1] = formatted[1].padEnd(minPrecision, "0");
        }
    }
    return formatted[1] ? formatted.join(decimalPoint) : formatted[0];
}

const _INVERTDICT = Object.freeze({
    1e-1: 1e1,
    1e-2: 1e2,
    1e-3: 1e3,
    1e-4: 1e4,
    1e-5: 1e5,
    1e-6: 1e6,
    1e-7: 1e7,
    1e-8: 1e8,
    1e-9: 1e9,
    1e-10: 1e10,
    2e-1: 5,
    2e-2: 5e1,
    2e-3: 5e2,
    2e-4: 5e3,
    2e-5: 5e4,
    2e-6: 5e5,
    2e-7: 5e6,
    2e-8: 5e7,
    2e-9: 5e8,
    2e-10: 5e9,
    5e-1: 2,
    5e-2: 2e1,
    5e-3: 2e2,
    5e-4: 2e3,
    5e-5: 2e4,
    5e-6: 2e5,
    5e-7: 2e6,
    5e-8: 2e7,
    5e-9: 2e8,
    5e-10: 2e9,
});

/**
 * @param {number} value
 * @returns {number}
 */
function invertFloat(value) {
    let res = /** @type {Record<number, number>} */ (_INVERTDICT)[value];
    if (res === undefined) {
        const [coeff, expt] = value.toExponential().split("e").map(Number.parseFloat);
        res = Number.parseFloat(`${coeff}e${-expt}`) / coeff ** 2;
    }
    return res;
}
