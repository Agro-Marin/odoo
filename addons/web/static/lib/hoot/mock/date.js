/** @odoo-module */

import {
    getTimeOffset,
    isTimeFrozen,
    resetTimeOffset,
} from "@odoo/hoot-dom-helpers-time";

import { createMock, HootError, isNil } from "../hoot_utils.js";
import { ensureTest } from "../main_runner.js";

/**
 * @typedef DateSpecs
 * @property {number} [year]
 * @property {number} [month]
 * @property {number} [day]
 * @property {number} [hour]
 * @property {number} [minute]
 * @property {number} [second]
 * @property {number} [millisecond]
 */

const { Date, Intl } = globalThis;
const { now: $now, UTC: $UTC } = Date;
const { DateTimeFormat, Locale } = Intl;

/**
 * @param {Date} baseDate
 */
function computeTimeZoneOffset(baseDate) {
    const utcDate = new Date(
        baseDate.toLocaleString(DEFAULT_LOCALE, { timeZone: "UTC" }),
    );
    const tzDate = new Date(
        baseDate.toLocaleString(DEFAULT_LOCALE, { timeZone: timeZoneName }),
    );
    return (utcDate - tzDate) / 60000;
}

/**
 * @param {number} id
 */
function getDateParams() {
    return [
        ...dateParams.slice(0, -1),
        dateParams.at(-1) + getTimeStampDiff() + getTimeOffset(),
    ];
}

function getTimeStampDiff() {
    return isTimeFrozen() ? 0 : $now() - dateTimeStamp;
}

/**
 * @param {string | DateSpecs} dateSpecs
 */
function parseDateParams(dateSpecs) {
    /** @type {DateSpecs} */
    const specs =
        (typeof dateSpecs === "string"
            ? dateSpecs.match(DATE_REGEX)?.groups
            : dateSpecs) || {};
    return [
        specs.year ?? DEFAULT_DATE[0],
        (specs.month ?? DEFAULT_DATE[1]) - 1,
        specs.day ?? DEFAULT_DATE[2],
        specs.hour ?? DEFAULT_DATE[3],
        specs.minute ?? DEFAULT_DATE[4],
        specs.second ?? DEFAULT_DATE[5],
        specs.millisecond ?? DEFAULT_DATE[6],
    ].map(Number);
}

/**
 * @param {typeof dateParams} newDateParams
 */
function setDateParams(newDateParams) {
    dateParams = newDateParams;
    dateTimeStamp = $now();

    resetTimeOffset();
}

/**
 * @param {string | number | null | undefined} tz
 */
function setTimeZone(tz) {
    if (typeof tz === "string") {
        if (!tz.includes("/")) {
            throw new HootError(
                `invalid time zone: must be in the format <Country/...Location>`,
            );
        }

        timeZoneName = tz;
        timeZoneOffset = computeTimeZoneOffset;
    } else if (typeof tz === "number") {
        timeZoneOffset = tz * -60;
    } else {
        timeZoneName = null;
        timeZoneOffset = null;
    }

    for (const callback of timeZoneChangeCallbacks) {
        callback(tz ?? DEFAULT_TIMEZONE_NAME);
    }
}

class MockDateTimeFormat extends DateTimeFormat {
    constructor(locales, options) {
        super(locales, {
            ...options,
            timeZone: options?.timeZone ?? timeZoneName ?? DEFAULT_TIMEZONE_NAME,
        });
    }

    /** @type {Intl.DateTimeFormat["format"]} */
    format(date) {
        return super.format(date || new MockDate());
    }

    resolvedOptions() {
        return {
            ...super.resolvedOptions(),
            timeZone: timeZoneName ?? DEFAULT_TIMEZONE_NAME,
            locale: locale ?? DEFAULT_LOCALE,
        };
    }
}

const DATE_REGEX =
    /(?<year>\d{4})[/-](?<month>\d{2})[/-](?<day>\d{2})([\sT]+(?<hour>\d{2}):(?<minute>\d{2}):(?<second>\d{2})(\.(?<millisecond>\d{3}))?)?/;
const DEFAULT_DATE = [2019, 2, 11, 9, 30, 0, 0];
const DEFAULT_LOCALE = "en-US";
const DEFAULT_TIMEZONE_NAME = "Europe/Brussels";
const DEFAULT_TIMEZONE_OFFSET = -60;

/** @type {((tz: string | number) => any)[]} */
const timeZoneChangeCallbacks = [];

let dateParams = DEFAULT_DATE;
let dateTimeStamp = $now();
/** @type {string | null} */
let locale = null;
/** @type {string | null} */
let timeZoneName = null;
/** @type {number | ((date: Date) => number) | null} */
let timeZoneOffset = null;

export function cleanupDate() {
    setDateParams(DEFAULT_DATE);
    locale = null;
    timeZoneName = null;
    timeZoneOffset = null;
}

/**
 * @param {string | DateSpecs} [date]
 * @param {string | number | null} [tz]
 */
export function mockDate(date, tz) {
    ensureTest("mockDate");
    setDateParams(date ? parseDateParams(date) : DEFAULT_DATE);
    if (!isNil(tz)) {
        setTimeZone(tz);
    }
}

/**
 * @param {string} newLocale
 */
export function mockLocale(newLocale) {
    ensureTest("mockLocale");
    locale = newLocale;

    if (!isNil(locale) && isNil(timeZoneName)) {
        const firstAvailableTZ = new Locale(locale).timeZones?.[0];
        if (!isNil(firstAvailableTZ)) {
            setTimeZone(firstAvailableTZ);
        }
    }
}

/**
 * @param {string | number | null} [tz]
 */
export function mockTimeZone(tz) {
    ensureTest("mockTimeZone");
    setTimeZone(tz);
}

/**
 * @param {(tz: string | number) => any} callback
 */
export function onTimeZoneChange(callback) {
    timeZoneChangeCallbacks.push(callback);
}

export class MockDate extends Date {
    constructor(...args) {
        if (args.length === 1) {
            super(args[0]);
        } else {
            const params = getDateParams();
            for (let i = 0; i < params.length; i++) {
                args[i] ??= params[i];
            }
            super($UTC(...args));
        }
    }

    getTimezoneOffset() {
        const offset = timeZoneOffset ?? DEFAULT_TIMEZONE_OFFSET;
        return typeof offset === "function" ? offset(this) : offset;
    }

    static now() {
        return new MockDate().getTime();
    }
}

export const MockIntl = createMock(Intl, {
    DateTimeFormat: { value: MockDateTimeFormat },
});
