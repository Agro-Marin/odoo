// @ts-check
/** @odoo-module native */

/** @module @web/core/l10n/dates - Luxon-based date/datetime parsing, formatting, serialization, and locale-aware week helpers */

import { localization } from "@web/core/l10n/localization";
import { DateTime, Duration, Settings } from "@web/core/l10n/luxon";
import { _t } from "@web/core/l10n/translation";
import { memoize } from "@web/core/utils/functions";

import { isInRange, today } from "./date_utils.js";

// Re-export extracted modules for backward compatibility
export {
    deserializeDate,
    deserializeDateTime,
    serializeDate,
    serializeDateTime,
} from "./date_serialization.js";
export {
    areDatesEqual,
    clampDate,
    getEndOfLocalWeek,
    getLocalYearAndWeek,
    getStartOfLocalWeek,
    isInRange,
    today,
} from "./date_utils.js";

/**
 * @typedef ConversionOptions
 * @property {string} [format]
 * @property {string} [tz]
 *
 * @typedef {[NullableDateTime, NullableDateTime]} NullableDateRange
 *
 * A Luxon ``DateTime`` or an "empty" sentinel. ``null`` and ``false`` both mean
 * "no value" across the date API (``false`` is what an unset Odoo date/datetime
 * field carries); callers must narrow before reading DateTime members. Was
 * ``any``, which silently opted the whole date API out of ``@ts-check``.
 * @typedef {DateTime | null | false} NullableDateTime
 */

/**
 * @typedef ConversionLocalOptions
 * @property {boolean} [showSeconds]
 * @property {boolean} [showTime]
 * @property {boolean} [showDate]
 * @property {string} [tz]
 */

/**
 * Limits defining a valid date (server only understands 4-digit years).
 * Computed once and cached — each getter is hit ~10x per parseDateTime.
 */
let minValidDate;
let maxValidDate;
export function getMinValidDate() {
    return (minValidDate ??= DateTime.fromObject({ year: 1000 }));
}
export function getMaxValidDate() {
    return (maxValidDate ??= DateTime.fromObject({ year: 9999 }).endOf("year"));
}

const nonAlphaRegex = /[^a-z]/gi;
const nonDigitRegex = /[^\d]/g;

/** @type {Record<string, string>} */
const normalizeFormatTable = {
    // Python strftime to luxon.js conversion table
    a: "ccc",
    A: "cccc",
    b: "MMM",
    B: "MMMM",
    d: "dd",
    H: "HH",
    I: "hh",
    // Python ``%j`` is the zero-padded 3-digit day of year ("065", "005");
    // luxon ``o`` is unpadded ("65", "5"), so pad it with ``ooo``.
    j: "ooo",
    m: "MM",
    M: "mm",
    p: "a",
    S: "ss",
    W: "WW",
    w: "c",
    y: "yy",
    Y: "yyyy",
    c: "ccc MMM d HH:mm:ss yyyy",
    x: "MM/dd/yy",
    X: "HH:mm:ss",
};

/** @type {Record<string, string>} */
const smartDateUnits = {
    d: "days",
    m: "months",
    w: "weeks",
    y: "years",
    H: "hours",
    M: "minutes",
    S: "seconds",
};
/** @type {Record<string, number>} */
const smartWeekdays = {
    monday: 1,
    tuesday: 2,
    wednesday: 3,
    thursday: 4,
    friday: 5,
    saturday: 6,
    sunday: 7,
};

export class ConversionError extends Error {
    name = "ConversionError";
}

//-----------------------------------------------------------------------------
// Helpers
//-----------------------------------------------------------------------------

/**
 * Returns whether the given DateTime is valid (between 1000-01-01 and 9999-12-31).
 * @param {NullableDateTime} date
 */
function isValidDate(date) {
    return (
        date && date.isValid && isInRange(date, [getMinValidDate(), getMaxValidDate()])
    );
}

/**
 * Smart date inputs are shortcuts to write dates quicker.
 *
 * @param {string} value
 * @returns {NullableDateTime}
 */
function parseSmartDateInput(value) {
    const terms = value.split(/\s+/);
    if (!terms.length) {
        return null;
    }
    let now = DateTime.local().startOf("second");
    if (terms[0] === "today") {
        terms.shift();
        now = now.startOf("day");
    } else if (terms[0] === "now") {
        terms.shift();
    } else if (terms.length === 1 && /^[=+-]\d+$/.test(terms[0])) {
        terms[0] += "d";
    }

    for (let i = 0; i < terms.length; i++) {
        const term = terms[i];
        const operator = term[0];
        if (term.length < 3 || !["+", "-", "="].includes(operator)) {
            return null;
        }

        const dayname = term.slice(1);
        if (Object.hasOwn(smartWeekdays, dayname) || dayname === "week_start") {
            const { weekStart } = localization;
            const weekdayNumber =
                dayname === "week_start" ? weekStart : smartWeekdays[dayname];
            let weekdayOffset =
                ((weekdayNumber - weekStart + 7) % 7) -
                ((now.weekday - weekStart + 7) % 7);
            if (operator === "+" || operator === "-") {
                if (weekdayOffset > 0 && operator === "-") {
                    weekdayOffset -= 7;
                } else if (weekdayOffset < 0 && operator === "+") {
                    weekdayOffset += 7;
                }
            } else {
                now = now.startOf("day");
            }
            now = now.plus({ days: weekdayOffset });
            continue;
        }

        try {
            const field_name = smartDateUnits[/** @type {string} */ (term.at(-1))];
            const number = Number.parseInt(term.slice(1, -1), 10);
            if (!field_name || Number.isNaN(number)) {
                return null;
            }
            if (operator === "+") {
                now = now.plus({ [field_name]: number });
            } else if (operator === "-") {
                now = now.minus({ [field_name]: number });
            } else if (operator === "=") {
                if (
                    field_name === "seconds" ||
                    field_name === "minutes" ||
                    field_name === "hours"
                ) {
                    now = now.startOf(/** @type {any} */ (field_name));
                } else if (field_name === "weeks") {
                    return null;
                } else {
                    now = now.startOf("day");
                }
                now = now.set({ [field_name]: number });
            }
        } catch {
            return null;
        }
    }

    return now;
}

/**
 * Removes duplicate subsequent alphabetic characters.
 * @type {(str: string) => string}
 */
const stripAlphaDupes = memoize(function stripAlphaDupes(str) {
    return str.replace(/[a-z]/gi, (letter, index, str) =>
        letter === str[index - 1] ? "" : letter,
    );
});

/**
 * Convert Python strftime to escaped luxon.js format.
 * @type {(format: string) => string}
 */
export const strftimeToLuxonFormat = memoize(function strftimeToLuxonFormat(format) {
    const output = [];
    let inToken = false;
    for (let index = 0; index < format.length; ++index) {
        let character = format[index];
        if (character === "%" && !inToken) {
            inToken = true;
            continue;
        }
        if (/[a-z]/gi.test(character)) {
            if (inToken && normalizeFormatTable[character] !== undefined) {
                character = normalizeFormatTable[character];
            } else {
                character = `'${character}'`;
            }
        }
        output.push(character);
        inToken = false;
    }
    return output.join("");
});

//-----------------------------------------------------------------------------
// Formatting
//-----------------------------------------------------------------------------

// Base locale format objects, precomputed once instead of spread + mutated on
// every toLocaleDateString/toLocaleDateTimeString call.
const DATE_MED_NO_YEAR = { ...DateTime.DATE_MED };
delete DATE_MED_NO_YEAR.year;
const DATETIME_MED_NO_SECONDS = { ...DateTime.DATETIME_MED_WITH_SECONDS };
delete DATETIME_MED_NO_SECONDS.second;

/**
 * Current year in the default timezone, memoized for the current local day.
 * Avoids building two luxon DateTimes (`today()`) per formatted value just to
 * compare `.year`. The memo is keyed on the [start, end) timestamps of the
 * day it was computed for, so it also recomputes when the clock is moved
 * backwards (e.g. mocked dates in tests).
 */
let currentYear;
let currentYearDayStart = 0;
let currentYearDayEnd = 0;
function getCurrentYear() {
    const now = Date.now();
    if (now < currentYearDayStart || now >= currentYearDayEnd) {
        const startOfToday = today();
        currentYear = startOfToday.year;
        currentYearDayStart = startOfToday.ts;
        currentYearDayEnd = startOfToday.plus({ day: 1 }).ts;
    }
    return currentYear;
}

/**
 * @param {NullableDateTime} value
 * @param {ConversionOptions} [options={}]
 */
export function formatDate(value, options = {}) {
    if (!value) {
        return "";
    }
    const format = options.format || localization.dateFormat;
    return value.toFormat(format);
}

/**
 * @param {NullableDateTime} value
 * @param {ConversionOptions} [options={}]
 */
export function formatDateTime(value, options = {}) {
    if (!value) {
        return "";
    }
    const format = options.format || localization.dateTimeFormat;
    return value.setZone(options.tz || "default").toFormat(format);
}

/**
 * Format a DateTime to a locale date string (e.g. "Jan 31, 2024").
 * Current year is omitted.
 *
 * @param {NullableDateTime} value
 */
export function toLocaleDateString(value) {
    if (!value) {
        return "";
    }
    const format =
        getCurrentYear() === value.year ? DATE_MED_NO_YEAR : DateTime.DATE_MED;
    return value.toLocaleString(format);
}

/**
 * Format a DateTime to a locale datetime string (e.g. "Jan 31, 2024, 12:00 AM").
 *
 * @param {NullableDateTime} value
 * @param {ConversionLocalOptions} [options]
 */
export function toLocaleDateTimeString(
    value,
    options = { showDate: true, showTime: true, showSeconds: false },
) {
    if (!value) {
        return "";
    }
    const format = options.showSeconds
        ? { ...DateTime.DATETIME_MED_WITH_SECONDS }
        : { ...DATETIME_MED_NO_SECONDS };
    if (options.showDate === false) {
        delete format.day;
        delete format.month;
        delete format.year;
    }
    if (options.showTime === false) {
        delete format.hour;
        delete format.minute;
    }
    if (getCurrentYear() === value.year) {
        delete format.year;
    }
    return value.setZone(options.tz || "default").toLocaleString(format);
}

/**
 * Converts duration in seconds to human-readable format.
 *
 * @param {number} seconds
 * @param {boolean} showFullDuration
 * @returns {string}
 */
export function formatDuration(seconds, showFullDuration) {
    const displayStyle = showFullDuration ? "long" : "narrow";
    const numberOfValuesToDisplay = showFullDuration ? 2 : 1;
    /** @type {Array<"years" | "months" | "days" | "hours" | "minutes">} */
    const durationKeys = ["years", "months", "days", "hours", "minutes"];
    /** Plural Luxon key -> singular Intl "unit" identifier. */
    const intlUnitByKey = {
        years: "year",
        months: "month",
        days: "day",
        hours: "hour",
        minutes: "minute",
    };

    // Work on the magnitude and remember the sign separately. The minimum
    // granularity is one minute: sub-minute durations (including negative or
    // zero ones) are floored to whole minutes.
    const sign = seconds < 0 ? -1 : 1;
    let magnitude = Math.abs(Math.trunc(seconds));
    magnitude -= magnitude % 60;

    const duration = Duration.fromObject({ seconds: magnitude }).shiftTo(
        ...durationKeys,
    );
    // Use luxon's public default-locale setting instead of reaching into the
    // private `duration.loc.locale`. `Duration.fromObject` above carried no
    // explicit locale, so it resolves to exactly this value (or, when unset,
    // the runtime default — which `undefined` also selects for Intl).
    const locale = Settings.defaultLocale || undefined;

    /**
     * Formats a single unit value using the locale, avoiding `toHuman` (whose
     * output we would otherwise have to split on a comma — a separator that
     * does not exist in "and"-joined locales such as `ar`, which would make
     * every unit show regardless of `numberOfValuesToDisplay`).
     *
     * @param {number} value
     * @param {"years" | "months" | "days" | "hours" | "minutes"} key
     * @returns {string}
     */
    const formatUnit = (value, key) => {
        let formatted = new Intl.NumberFormat(locale, {
            style: "unit",
            unit: intlUnitByKey[key],
            unitDisplay: displayStyle,
        }).format(value);
        // In narrow English, both "month" and "minute" render as "…m"; the
        // original code disambiguated months as "…M". Only uppercase the
        // trailing unit letter — a blanket replace of the first "m" could hit
        // the value part or a wider unit spelling (e.g. "5 mo" in some CLDR
        // variants).
        if (!showFullDuration && key === "months" && (locale || "").includes("en")) {
            formatted = formatted.replace(/m(?=\W*$)/, "M");
        }
        return formatted;
    };

    // Take the first N non-zero units, largest first.
    /** @type {Array<["years" | "months" | "days" | "hours" | "minutes", number]>} */
    const parts = [];
    for (const key of durationKeys) {
        const value = duration.get(key);
        if (value) {
            parts.push([key, value]);
            if (parts.length >= numberOfValuesToDisplay) {
                break;
            }
        }
    }

    if (!parts.length) {
        // Below the minimum granularity: report "0 minutes".
        return formatUnit(0, "minutes");
    }

    // Carry the sign on the leading (largest) unit only.
    return parts
        .map(([key, value], index) =>
            formatUnit(index === 0 ? sign * value : value, key),
        )
        .join(", ");
}

//-----------------------------------------------------------------------------
// Parsing
//-----------------------------------------------------------------------------

/**
 * @param {string} value
 * @param {ConversionOptions} [options={}]
 */
export function parseDate(value, options = {}) {
    const parsed = parseDateTime(value, {
        ...options,
        format: options.format || localization.dateFormat,
    });
    return parsed ? parsed.startOf("day") : null;
}

/**
 * Parses a string value to a Luxon DateTime object.
 * Tries multiple strategies: user format, smart date input, partial formats, ISO, SQL.
 *
 * @param {string} value
 * @param {ConversionOptions} [options={}]
 * @returns {NullableDateTime}
 */
export function parseDateTime(value, options = {}) {
    if (!value) {
        return null;
    }

    const fmt = options.format || localization.dateTimeFormat;
    /** @type {{ setZone: boolean, zone: string, numberingSystem?: string }} */
    const parseOpts = {
        setZone: true,
        zone: options.tz || "default",
    };
    const switchToLatin =
        Settings.defaultNumberingSystem !== "latn" && /[0-9]/.test(value);

    if (switchToLatin) {
        parseOpts.numberingSystem = "latn";
    }

    let result = DateTime.fromFormat(value, fmt, parseOpts);

    if (!isValidDate(result)) {
        result = parseSmartDateInput(value);
    }

    if (!isValidDate(result)) {
        const fmtWoZero = stripAlphaDupes(fmt);
        result = DateTime.fromFormat(value, fmtWoZero, parseOpts);
    }

    if (!isValidDate(result)) {
        const digitList = value.split(nonDigitRegex).filter(Boolean);
        const fmtList = fmt.split(nonAlphaRegex).filter(Boolean);
        const valWoSeps = digitList.join("");

        let carry = 0;
        const fmtWoSeps = fmtList
            .map((part, i) => {
                const digitLength = (digitList[i] || "").length;
                const actualPart = part.slice(0, digitLength + carry);
                carry += digitLength - actualPart.length;
                return actualPart;
            })
            .join("");

        result = DateTime.fromFormat(valWoSeps, fmtWoSeps, parseOpts);
    }

    if (!isValidDate(result)) {
        const valueDigits = value.replace(nonDigitRegex, "");
        if (valueDigits.length > 4) {
            result = DateTime.fromISO(value, parseOpts);
            if (!isValidDate(result)) {
                result = DateTime.fromSQL(value, parseOpts);
            }
        }
    }

    if (!isValidDate(result)) {
        throw new ConversionError(_t("'%s' is not a correct date or datetime", value));
    }

    if (switchToLatin) {
        result = result.reconfigure({
            numberingSystem: Settings.defaultNumberingSystem,
        });
    }

    return result.setZone(options.tz || "default");
}
