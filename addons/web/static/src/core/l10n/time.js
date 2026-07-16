// @ts-check
/** @odoo-module native */

/** @module @web/core/l10n/time - Time class for 24h time representation with locale-aware parsing */

import { localization } from "@web/core/l10n/localization";
import { DateTime } from "@web/core/l10n/luxon";

const NUMERAL_MAPS = [
    "٠١٢٣٤٥٦٧٨٩", // Arabic
    "۰۱۲۳۴۵۶۷۸۹",
    "०१२३४५६७८९", // Devanagari (Hindi)
    "๐๑๒๓๔๕๖๗๘๙", // Thai
    "零一二三四五六七八九", // Chinese/Japanese/Korean
];

/**
 * A representation of a specific time in a 24 hour format
 */
export class Time {
    /**
     * This method will return a Time object contructed
     * differently depending on the type of {value}
     *
     * - If value is already a Time object, it returns it.
     * - If value is null, undefined or false, it returns null.
     * - If value is a string, it will try to parse it, @see {parseTime}
     * - If value is an object, it will use its [hour], [minute] and [second] properties
     * - Otherwise, return a new Time with default values
     *
     * @param {any} value
     * @returns {Time|null}
     */
    static from(value) {
        if (value === null || value === undefined || value === false) {
            return null;
        } else if (value instanceof Time) {
            return value;
        } else if (typeof value === "string") {
            return parseTime(value, true);
        } else if (typeof value === "object") {
            return new Time(value);
        } else {
            return null;
        }
    }

    /**
     * @param {{ hour?: number, minute?: number, second?: number }} [params]
     */
    constructor({ hour = 0, minute = 0, second = 0 } = {}) {
        /**@type {number} */
        this.hour = hour;
        /**@type {number} */
        this.minute = minute;
        /**@type {number} */
        this.second = second;

        /**
         * @private
         * @type {boolean}
         */
        this._is24HourFormat = is24HourFormat();

        /**
         * @private
         * @type {boolean}
         */
        this._isMeridiemFormat = isMeridiemFormat();
    }

    /**
     * @param {number} rounding
     */
    roundMinutes(rounding) {
        const rounded = Math.round(this.minute / rounding) * rounding;
        if (rounded >= 60) {
            if (this.hour >= 23) {
                // Rounding up would spill past midnight and wrap to 00:00 the
                // same day (~24h back). Round down to the last valid slot
                // instead (e.g. 23:58 -> 23:55 with rounding 5).
                this.minute = Math.floor(59 / rounding) * rounding;
            } else {
                this.hour = this.hour + 1;
                this.minute = 0;
            }
        } else {
            this.minute = rounded;
        }
    }

    /**
     * @returns {Time}
     */
    copy() {
        return new Time(this);
    }

    /**
     * @param {Time} other
     * @param {boolean} [checkSeconds=false]
     * @returns {boolean}
     */
    equals(other, checkSeconds = false) {
        return (
            other &&
            this.hour === other.hour &&
            this.minute === other.minute &&
            (!checkSeconds || this.second === other.second)
        );
    }

    /**
     * Format the time in 24h or 12h (with meridiem) per the current
     * localization time format.
     *
     * @param {boolean} [showSeconds=false]
     * @returns {string}
     */
    toString(showSeconds = false) {
        const hourFormat = this._is24HourFormat ? "H" : "h";
        const secondFormat = showSeconds ? ":ss" : "";
        const meridiemFormat = this._isMeridiemFormat ? "a" : "";
        return this.toDateTime()
            .toFormat(`${hourFormat}:mm${secondFormat}${meridiemFormat}`)
            .toLowerCase();
    }

    toDateTime() {
        return DateTime.fromObject(this.toObject());
    }

    /**
     * Returns the time as an Object
     * @returns {{hour: number, minute: number, second: number}}
     */
    toObject() {
        return {
            hour: this.hour,
            minute: this.minute,
            second: this.second,
        };
    }
}

/**
 * Returns whether the given format is a 24-hour format.
 * Falls back to localization time format if none is given.
 *
 * @param {string} [format]
 */
export function is24HourFormat(format) {
    return /H/.test(format || localization.timeFormat);
}

/**
 * Returns whether the given format uses a meridiem suffix (AM/PM).
 * Falls back to localization time format if none is given.
 *
 * @param {string} [format]
 */
function isMeridiemFormat(format) {
    return /a/.test(format || localization.timeFormat);
}

/**
 * Tries to parse a Time object from a time string
 * representation such as:
 * "10:15"  -> 10:15:00
 * "2h5"    -> 02:50:00
 * "1015"   -> 10:15:00
 * "125"    -> 12:50:00
 * "315"    -> 03:15:00
 * "5:15pm" -> 17:15:00
 *
 * Returns null if the value could not be parsed.
 *
 * @param {string} value
 * @param {boolean} [parseSeconds]
 * @returns {Time | null}
 */
export function parseTime(value, parseSeconds) {
    const { isPm, isAm } = meridiemCheck(value);
    const normalized = normalizeTimeStr(value);

    if (!normalized) {
        return null;
    }
    value = normalized;

    let hour = 0;
    let minute = 0;
    let second = 0;

    const parse = (/** @type {string} */ str) => {
        if (!str.length) {
            return 0;
        } else if (/^[\d]+$/.test(str)) {
            return Number.parseInt(str, 10);
        } else {
            return NaN;
        }
    };

    const parts = value.split(/[\s:]/g);
    if (parts.length > 3) {
        return null;
    } else if (parts.length === 3) {
        if (!parseSeconds) {
            return null;
        }
        hour = parse(parts[0]);
        minute = parse(parts[1].padEnd(2, "0"));
        second = parse(parts[2].padEnd(2, "0"));
    } else if (parts.length === 2) {
        hour = parse(parts[0]);
        minute = parse(parts[1].padEnd(2, "0"));
    } else if (parts.length === 1) {
        const raw = parts[0];

        const pickSolution = (/** @type {string[][]} */ ...solutions) => {
            for (const solution of solutions) {
                const h = parse(solution[0]);
                // "24" is only a valid hour with no minutes (ISO 8601
                // end-of-day). Reject a 24-hour candidate that carries minutes
                // so e.g. "240" resolves to the ["2", "40"] reading (2:40)
                // instead of being consumed as hour 24 → 00:00.
                if (h < 24 || (h === 24 && !solution[1])) {
                    hour = h;
                    if (solution[1]) {
                        minute = parse(solution[1].padEnd(2, "0"));
                    }
                    break;
                }
            }
        };

        if (raw.length === 1) {
            hour = parse(raw);
        } else if (raw.length === 2) {
            pickSolution([raw], [raw[0], raw[1]]);
        } else if (raw.length === 3) {
            pickSolution([raw.slice(0, 2), raw[2]], [raw[0], raw.slice(1)]);
        } else if (raw.length === 4) {
            hour = parse(raw.slice(0, 2));
            minute = parse(raw.slice(2));
        } else if (raw.length > 4 && raw.length <= 6) {
            if (!parseSeconds) {
                return null;
            }
            hour = parse(raw.slice(0, 2));
            minute = parse(raw.slice(2, 4));
            second = parse(raw.slice(4).padEnd(2, "0"));
        } else {
            return null;
        }
    }

    if (isPm && hour < 12) {
        hour += 12;
    } else if (isAm && hour === 12) {
        hour = 0;
    }

    if (
        hour >= 0 &&
        hour <= 24 &&
        minute >= 0 &&
        minute < 60 &&
        second >= 0 &&
        second < 60
    ) {
        if (hour === 24) {
            // "24" is only a valid hour as ISO 8601 end-of-day ("24:00:00");
            // accepting "24:30" would silently turn it into "00:30".
            if (minute || second) {
                return null;
            }
            hour = 0;
        }
        return new Time({ hour, minute, second });
    } else {
        return null;
    }
}

/**
 * - Converts other languages numeral systems to western arabic numbers
 * - Replaces with ":" all chains of non-numeric characters between numbers
 * - Removes all trailing non-numeric characters
 *
 * @param {string} timeStr
 * @returns {string|false}
 */
function normalizeTimeStr(timeStr) {
    if (typeof timeStr !== "string") {
        return false;
    }

    timeStr = timeStr.trim().toLowerCase();

    for (const map of NUMERAL_MAPS) {
        for (let i = 0; i < map.length; i++) {
            timeStr = timeStr.replaceAll(map[i], String(i));
        }
    }

    return timeStr.replace(/^\D+|\D+$/g, "").replace(/\D+/g, ":");
}

/**
 * @param {string} timeStr
 * @returns {{ isPm: boolean, isAm: boolean }}
 */
function meridiemCheck(timeStr) {
    const amPmMatch =
        typeof timeStr === "string" ? timeStr.toLowerCase().match(/(am|pm)/g) : null;
    return {
        isPm: amPmMatch?.[0] === "pm",
        isAm: amPmMatch?.[0] === "am",
    };
}
