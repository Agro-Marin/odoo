// @ts-check
/** @odoo-module native */

/** @module @web/core/py_js/py_date */

import { DateTime } from "@web/core/l10n/luxon";

import { bindArgs } from "./py_args.js";
import {
    assert,
    assertYearInRange,
    daysInMonth,
    divmod,
    fmt2,
    fmt4,
    isLeap,
    tmxxx,
    ValueError,
    ymd2ord,
} from "./py_date_helpers.js";
import { PyTimeDelta } from "./py_timedelta.js";

export { PyTimeDelta } from "./py_timedelta.js";

export class NotSupportedError extends Error {}

/**
 * @param {string} format
 * @param {Record<string, () => string>} converters
 * @returns {string}
 */
const COMPOSITE_DIRECTIVES = {
    c: "%a %b %e %H:%M:%S %Y",
    x: "%m/%d/%y",
    X: "%H:%M:%S",
};

const DIRECTIVE_RE = /%(%|[A-Za-z])/g;

/**
 * @param {string} format
 * @param {Record<string, (this: any) => string>} converters
 * @returns {string}
 */
function strftime(format, converters) {
    const expanded = format.replace(
        DIRECTIVE_RE,
        (/** @type {string} */ m, /** @type {string} */ c) =>
            c in COMPOSITE_DIRECTIVES
                ? /** @type {Record<string, string>} */ (COMPOSITE_DIRECTIVES)[c]
                : m,
    );
    return expanded.replace(
        DIRECTIVE_RE,
        (/** @type {string} */ m, /** @type {string} */ c) => {
            if (c === "%") {
                return "%";
            }
            if (c in converters) {
                return converters[c]();
            }
            throw new ValueError(`No known conversion for ${m}`);
        },
    );
}

/**
 * @param {number} hour24
 * @returns {string}
 */
function fmt12(hour24) {
    const h = hour24 % 12;
    return fmt2(h === 0 ? 12 : h);
}

/**
 * @param {number} hour24
 * @returns {string}
 */
function ampm(hour24) {
    return hour24 < 12 ? "AM" : "PM";
}

const WEEKDAY_ABBR = "Mon Tue Wed Thu Fri Sat Sun".split(" ");
const WEEKDAY_FULL = "Monday Tuesday Wednesday Thursday Friday Saturday Sunday".split(
    " ",
);
const MONTH_ABBR = "Jan Feb Mar Apr May Jun Jul Aug Sep Oct Nov Dec".split(" ");
const MONTH_FULL =
    "January February March April May June July August September October November December".split(
        " ",
    );

/**
 * @param {number} year
 * @param {number} month
 * @param {number} day
 * @returns {Record<string, () => string>}
 */
function dateDirectives(year, month, day) {
    const ordinal = ymd2ord(year, month, day);
    const weekday = (ordinal + 6) % 7;
    const sundayFirst = (weekday + 1) % 7;
    const yearDay = ordinal - ymd2ord(year, 1, 1) + 1;
    return {
        Y: () => fmt4(year),
        y: () => fmt2(year % 100),
        m: () => fmt2(month),
        d: () => fmt2(day),
        e: () => String(day).padStart(2, " "),
        j: () => String(yearDay).padStart(3, "0"),
        w: () => String(sundayFirst),
        U: () => fmt2(Math.floor((yearDay + 6 - sundayFirst) / 7)),
        W: () => fmt2(Math.floor((yearDay + 6 - weekday) / 7)),
        a: () => WEEKDAY_ABBR[weekday],
        A: () => WEEKDAY_FULL[weekday],
        b: () => MONTH_ABBR[month - 1],
        B: () => MONTH_FULL[month - 1],
    };
}

/**
 * @param {string} name
 * @param {any} value
 */
function assertIntComponent(name, value) {
    if (typeof value !== "number" || !Number.isInteger(value)) {
        throw new ValueError(`${name} must be an integer`);
    }
}

/**
 * @param {any} year
 * @param {any} month
 * @param {any} day
 */
function assertDateComponents(year, month, day) {
    assertIntComponent("year", year);
    assertIntComponent("month", month);
    assertIntComponent("day", day);
    if (year < 1 || year > 9999) {
        throw new ValueError(`year must be in 1..9999, not ${year}`);
    }
    if (month < 1 || month > 12) {
        throw new ValueError("month must be in 1..12");
    }
    if (day < 1 || day > daysInMonth(year, month)) {
        throw new ValueError("day is out of range for month");
    }
}

/**
 * @param {any} hour
 * @param {any} minute
 * @param {any} second
 * @param {any} [microsecond=0]
 */
function assertTimeComponents(hour, minute, second, microsecond = 0) {
    assertIntComponent("hour", hour);
    assertIntComponent("minute", minute);
    assertIntComponent("second", second);
    assertIntComponent("microsecond", microsecond);
    if (hour < 0 || hour > 23) {
        throw new ValueError("hour must be in 0..23");
    }
    if (minute < 0 || minute > 59) {
        throw new ValueError("minute must be in 0..59");
    }
    if (second < 0 || second > 59) {
        throw new ValueError("second must be in 0..59");
    }
    if (microsecond < 0 || microsecond > 999999) {
        throw new ValueError("microsecond must be in 0..999999");
    }
}

export class PyDate {
    /**
     * ``datetime.date.today()``. The server evaluates it in a process pinned to
     * UTC (``odoo/_monkeypatches/__init__.py`` sets ``TZ`` and calls
     * ``tzset()``), so this one is UTC as well. ``contextToday`` is the
     * timezone-aware spelling.
     *
     * @returns {PyDate}
     */
    static today() {
        const now = new Date();
        return new PyDate(
            now.getUTCFullYear(),
            now.getUTCMonth() + 1,
            now.getUTCDate(),
        );
    }

    /**
     * ``context_today()``, which the server derives from the user's timezone
     * (``fields.Date.context_today``). Luxon's default zone is set to
     * ``user.tz`` at boot, so "now" in the default zone is that date.
     *
     * @returns {PyDate}
     */
    static contextToday() {
        const now = DateTime.now();
        return new PyDate(now.year, now.month, now.day);
    }

    /**
     * @param {Date} date
     * @returns {PyDate}
     */
    static convertDate(date) {
        const year = date.getFullYear();
        const month = date.getMonth() + 1;
        const day = date.getDate();
        return new PyDate(year, month, day);
    }

    /**
     * @param {number} year
     * @param {number} month
     * @param {number} day
     */
    constructor(year, month, day) {
        // Here rather than in `create()`, which is only the *literal* path:
        // `add()` and the relativedelta walk build their result straight
        // through the constructor, and those are the paths that overflow.
        assertYearInRange(year);
        this.year = year;
        this.month = month;
        this.day = day;
    }

    /**
     * @param {...any} args
     * @returns {PyDate}
     */
    static create(...args) {
        const { year, month, day } = bindArgs(args, ["year", "month", "day"], "date");
        assertDateComponents(year, month, day);
        return new PyDate(year, month, day);
    }

    /**
     * @param {PyTimeDelta} timedelta
     * @returns {PyDate}
     */
    add(timedelta) {
        const s = tmxxx(this.year, this.month, this.day + timedelta.days);
        return new PyDate(s.year, s.month, s.day);
    }

    /**
     * @param {any} other
     * @returns {boolean}
     */
    isEqual(other) {
        if (!(other instanceof PyDate)) {
            return false;
        }
        return (
            this.year === other.year &&
            this.month === other.month &&
            this.day === other.day
        );
    }

    /**
     * @param {...any} args
     * @returns {PyDate}
     */
    replace(...args) {
        const p = bindArgs(args, ["year", "month", "day"], "replace");
        return PyDate.create(
            p.year ?? this.year,
            p.month ?? this.month,
            p.day ?? this.day,
        );
    }

    /**
     * @param {string} format
     * @returns {string}
     */
    strftime(format) {
        return strftime(format, {
            ...dateDirectives(this.year, this.month, this.day),
            H: () => "00",
            M: () => "00",
            S: () => "00",
            f: () => "000000",
            I: () => "12",
            p: () => "AM",
        });
    }

    /**
     * @param {PyTimeDelta | PyDate} other
     * @returns {PyDate | PyTimeDelta}
     */
    subtract(other) {
        if (other instanceof PyTimeDelta) {
            return this.add(new PyTimeDelta(-other.days, 0, 0));
        }
        if (other instanceof PyDate) {
            return PyTimeDelta.create(this.toordinal() - other.toordinal());
        }
        throw new NotSupportedError(
            "date can only be subtracted from a date or a timedelta",
        );
    }

    /** @returns {string} */
    toJSON() {
        return this.strftime("%Y-%m-%d");
    }

    /**
     * @returns {string}
     */
    toString() {
        return this.toJSON();
    }

    /** @returns {number} */
    toordinal() {
        return ymd2ord(this.year, this.month, this.day);
    }

    /**
     * Monday is 0 and Sunday is 6, as in CPython.
     *
     * Ordinal 1 is 0001-01-01, a Monday, so the shift is +6 mod 7. Shipped
     * views really do call this -- `[('date', '>=', (context_today() -
     * datetime.timedelta(days=context_today().weekday())).strftime(...))]`
     * is the "since Monday" filter -- and without it the domain failed with
     * V8's "Function.prototype.apply was called on undefined".
     *
     * @returns {number}
     */
    weekday() {
        return (this.toordinal() + 6) % 7;
    }

    /**
     * Monday is 1 and Sunday is 7, as in CPython.
     *
     * @returns {number}
     */
    isoweekday() {
        return this.weekday() + 1;
    }

    /**
     * @returns {number}
     */
    valueOf() {
        return this.toordinal();
    }
}

const UNIX_EPOCH_ORDINAL = 719163;

export class PyDateTime {
    /**
     * @returns {PyDateTime}
     */
    static now() {
        const d = new Date();
        return new PyDateTime(
            d.getUTCFullYear(),
            d.getUTCMonth() + 1,
            d.getUTCDate(),
            d.getUTCHours(),
            d.getUTCMinutes(),
            d.getUTCSeconds(),
            0,
        );
    }

    /**
     * @param {Date} date
     * @returns {PyDateTime}
     */
    static convertDate(date) {
        const year = date.getFullYear();
        const month = date.getMonth() + 1;
        const day = date.getDate();
        const hour = date.getHours();
        const minute = date.getMinutes();
        const second = date.getSeconds();
        return new PyDateTime(year, month, day, hour, minute, second, 0);
    }

    /**
     * @param {...any} args
     * @returns {PyDateTime}
     */
    static create(...args) {
        const namedArgs = bindArgs(
            args,
            ["year", "month", "day", "hour", "minute", "second", "microsecond"],
            "datetime",
        );
        const year = namedArgs.year;
        const month = namedArgs.month;
        const day = namedArgs.day;
        const hour = namedArgs.hour ?? 0;
        const minute = namedArgs.minute ?? 0;
        const second = namedArgs.second ?? 0;
        const microsecond = namedArgs.microsecond ?? 0;
        assertDateComponents(year, month, day);
        assertTimeComponents(hour, minute, second, microsecond);
        return new PyDateTime(year, month, day, hour, minute, second, microsecond);
    }

    /**
     * @param {...any} args
     * @returns {PyDateTime}
     */
    static combine(...args) {
        const { date, time } = bindArgs(args, ["date", "time"], "combine");
        return PyDateTime.create(
            date.year,
            date.month,
            date.day,
            time.hour,
            time.minute,
            time.second,
        );
    }

    /**
     * @param {number} year
     * @param {number} month
     * @param {number} day
     * @param {number} hour
     * @param {number} minute
     * @param {number} second
     * @param {number} microsecond
     */
    constructor(year, month, day, hour, minute, second, microsecond) {
        assertYearInRange(year);
        this.year = year;
        this.month = month;
        this.day = day;
        this.hour = hour;
        this.minute = minute;
        this.second = second;
        this.microsecond = microsecond;
    }

    /**
     * @param {PyTimeDelta} timedelta
     * @returns {PyDateTime}
     */
    add(timedelta) {
        const s = tmxxx(
            this.year,
            this.month,
            this.day + timedelta.days,
            this.hour,
            this.minute,
            this.second + timedelta.seconds,
            this.microsecond + timedelta.microseconds,
        );
        return new PyDateTime(
            s.year,
            s.month,
            s.day,
            s.hour,
            s.minute,
            s.second,
            s.microsecond,
        );
    }

    /**
     * @param {any} other
     * @returns {boolean}
     */
    isEqual(other) {
        if (!(other instanceof PyDateTime)) {
            return false;
        }
        return (
            this.year === other.year &&
            this.month === other.month &&
            this.day === other.day &&
            this.hour === other.hour &&
            this.minute === other.minute &&
            this.second === other.second &&
            this.microsecond === other.microsecond
        );
    }

    /**
     * @param {...any} args
     * @returns {PyDateTime}
     */
    replace(...args) {
        const p = bindArgs(
            args,
            ["year", "month", "day", "hour", "minute", "second", "microsecond"],
            "replace",
        );
        return PyDateTime.create(
            p.year ?? this.year,
            p.month ?? this.month,
            p.day ?? this.day,
            p.hour ?? this.hour,
            p.minute ?? this.minute,
            p.second ?? this.second,
            p.microsecond ?? this.microsecond,
        );
    }

    /**
     * @param {string} format
     * @returns {string}
     */
    strftime(format) {
        return strftime(format, {
            ...dateDirectives(this.year, this.month, this.day),
            H: () => fmt2(this.hour),
            M: () => fmt2(this.minute),
            S: () => fmt2(this.second),
            f: () => String(this.microsecond).padStart(6, "0"),
            I: () => fmt12(this.hour),
            p: () => ampm(this.hour),
        });
    }

    /**
     * @param {PyTimeDelta | PyDateTime} other
     * @returns {PyDateTime | PyTimeDelta}
     */
    subtract(other) {
        if (other instanceof PyTimeDelta) {
            return this.add(other.negate());
        }
        if (other instanceof PyDateTime) {
            const daysDiff = this.toordinal() - other.toordinal();
            const secsDiff =
                this.hour * 3600 +
                this.minute * 60 +
                this.second -
                (other.hour * 3600 + other.minute * 60 + other.second);
            const usDiff = this.microsecond - other.microsecond;
            return PyTimeDelta.create({
                days: daysDiff,
                seconds: secsDiff,
                microseconds: usDiff,
            });
        }
        throw new NotSupportedError(
            "datetime can only be subtracted from a datetime or a timedelta",
        );
    }

    /** @returns {number} */
    toordinal() {
        return ymd2ord(this.year, this.month, this.day);
    }

    /**
     * Monday is 0 and Sunday is 6, as in CPython. `datetime` inherits this
     * from `date` there; here the two classes are siblings, so it is restated.
     *
     * @returns {number}
     */
    weekday() {
        return (this.toordinal() + 6) % 7;
    }

    /**
     * Monday is 1 and Sunday is 7, as in CPython.
     *
     * @returns {number}
     */
    isoweekday() {
        return this.weekday() + 1;
    }

    /**
     * @returns {string}
     */
    toJSON() {
        return this.strftime("%Y-%m-%d %H:%M:%S");
    }

    /**
     * @returns {string}
     */
    toString() {
        const base = this.strftime("%Y-%m-%d %H:%M:%S");
        return this.microsecond ? `${base}.${this.strftime("%f")}` : base;
    }

    /**
     * @returns {PyDateTime}
     */
    to_utc() {
        const utc = DateTime.fromObject({
            year: this.year,
            month: this.month,
            day: this.day,
            hour: this.hour,
            minute: this.minute,
            second: this.second,
        }).toUTC();
        return new PyDateTime(
            utc.year,
            utc.month,
            utc.day,
            utc.hour,
            utc.minute,
            utc.second,
            this.microsecond,
        );
    }

    /**
     * @returns {number}
     */
    valueOf() {
        return (
            (this.toordinal() - UNIX_EPOCH_ORDINAL) * 86400e6 +
            (this.hour * 3600 + this.minute * 60 + this.second) * 1e6 +
            this.microsecond
        );
    }
}

/**
 * A wall-clock time, deliberately **not** a ``PyDate``.
 *
 * ``PyTime`` used to extend ``PyDate`` (fixing year/month/day at 1900-01-01),
 * which made ``time`` pass every ``instanceof PyDate`` guard in the engine.
 * ``PyRelativeDelta.add`` is one such guard, so ``datetime.time(1, 2, 3) +
 * relativedelta(days=1)`` silently answered ``1900-01-02`` where the server's
 * ``safe_eval`` raises ``TypeError``. CPython agrees the two are unrelated:
 * ``isinstance(time(0, 0), date)`` is ``False``.
 */
export class PyTime {
    /**
     * @param {...any} args
     * @returns {PyTime}
     */
    static create(...args) {
        const namedArgs = bindArgs(args, ["hour", "minute", "second"], "time");
        const hour = namedArgs.hour ?? 0;
        const minute = namedArgs.minute ?? 0;
        const second = namedArgs.second ?? 0;
        assertTimeComponents(hour, minute, second);
        return new PyTime(hour, minute, second);
    }

    /**
     * @param {number} hour
     * @param {number} minute
     * @param {number} second
     */
    constructor(hour, minute, second) {
        this.hour = hour;
        this.minute = minute;
        this.second = second;
    }

    /**
     * @param {any} other
     * @returns {boolean}
     */
    isEqual(other) {
        if (!(other instanceof PyTime)) {
            return false;
        }
        return (
            this.hour === other.hour &&
            this.minute === other.minute &&
            this.second === other.second
        );
    }

    /**
     * @param {...any} args
     * @returns {PyTime}
     */
    replace(...args) {
        const p = bindArgs(args, ["hour", "minute", "second"], "replace");
        return PyTime.create(
            p.hour ?? this.hour,
            p.minute ?? this.minute,
            p.second ?? this.second,
        );
    }

    /**
     * @param {string} format
     * @returns {string}
     */
    strftime(format) {
        return strftime(format, {
            ...dateDirectives(1900, 1, 1),
            H: () => fmt2(this.hour),
            M: () => fmt2(this.minute),
            S: () => fmt2(this.second),
            f: () => "000000",
            I: () => fmt12(this.hour),
            p: () => ampm(this.hour),
        });
    }

    /** @returns {string} */
    toJSON() {
        return this.strftime("%H:%M:%S");
    }

    /** @returns {string} */
    toString() {
        return this.toJSON();
    }

    /**
     * @returns {number}
     */
    valueOf() {
        return this.hour * 3600 + this.minute * 60 + this.second;
    }
}

const DAYS_IN_YEAR = [31, 59, 90, 120, 151, 181, 212, 243, 273, 304, 334, 366];

const PERIOD_RANGES = {
    year: [1, 9999],
    month: [1, 12],
    day: [1, Infinity],
    hour: [0, 23],
    minute: [0, 59],
    second: [0, 59],
    microsecond: [0, 999999],
};

const RELATIVE_KEYS =
    "years months weeks days hours minutes seconds microseconds leapdays".split(" ");
const ABSOLUTE_KEYS =
    "year month day hour minute second microsecond weekday nlyearday yearday".split(
        " ",
    );

/**
 * @type {[string, string, number][]}
 */
const OVERFLOW_CASCADE = [
    ["microseconds", "seconds", 1000000],
    ["seconds", "minutes", 60],
    ["minutes", "hours", 60],
    ["hours", "days", 24],
    ["months", "years", 12],
];

/** @param {Record<string, any>} params */
function cascadeOverflow(params) {
    for (const [unit, coarser, limit] of OVERFLOW_CASCADE) {
        const value = params[unit];
        if (Math.abs(value) < limit) {
            continue;
        }
        const sign = Math.sign(value);
        params[unit] = ((value * sign) % limit) * sign;
        params[coarser] += Math.trunc((value * sign) / limit) * sign;
    }
}

/**
 * @param {Record<string, any>} params
 * @returns {boolean}
 */
function hasTimeComponent(params) {
    return Boolean(
        params.hours ||
        params.minutes ||
        params.seconds ||
        params.microseconds ||
        params.hour !== null ||
        params.minute !== null ||
        params.second !== null ||
        params.microsecond !== null,
    );
}

// dateutil's full signature, in order. The spec is both the positional
// binding order and the closed set of keywords relativedelta accepts.
const argsSpec = [
    "dt1",
    "dt2",
    "years",
    "months",
    "days",
    "leapdays",
    "weeks",
    "hours",
    "minutes",
    "seconds",
    "microseconds",
    "year",
    "month",
    "day",
    "weekday",
    "yearday",
    "nlyearday",
    "hour",
    "minute",
    "second",
    "microsecond",
];
export class PyRelativeDelta {
    /**
     * @param {...any} args
     * @returns {PyRelativeDelta}
     */
    static create(...args) {
        const params = bindArgs(args, argsSpec, "relativedelta");
        if ("dt1" in params) {
            throw new Error("relativedelta(dt1, dt2) is not supported for now");
        }
        for (const [period, [min, max]] of Object.entries(PERIOD_RANGES)) {
            if (period in params && params[period] !== null) {
                const val = params[period];
                assert(val >= min && val <= max, `${period} ${val} is out of range`);
            }
        }

        for (const key of RELATIVE_KEYS) {
            params[key] = params[key] || 0;
        }
        for (const key of ABSOLUTE_KEYS) {
            params[key] = key in params ? params[key] : null;
        }
        for (const key of ["years", "months"]) {
            if (!Number.isInteger(params[key])) {
                throw new ValueError(
                    "Non-integer years and months are ambiguous and not currently supported.",
                );
            }
        }
        if (params.weekday !== null) {
            if (
                !Number.isInteger(params.weekday) ||
                params.weekday < -7 ||
                params.weekday > 6
            ) {
                throw new ValueError(`invalid weekday (${params.weekday})`);
            }
            params.weekday = (params.weekday + 7) % 7;
        }
        params.days += 7 * params.weeks;
        params.leapDays = params.leapdays;

        let yearDay = 0;
        if (params.nlyearday) {
            yearDay = params.nlyearday;
        } else if (params.yearday) {
            yearDay = params.yearday;
            if (yearDay > 59) {
                params.leapDays = -1;
            }
        }

        if (yearDay) {
            const monthIndex = DAYS_IN_YEAR.findIndex((ydays) => yearDay <= ydays);
            if (monthIndex === -1) {
                throw new ValueError(`invalid year day (${yearDay})`);
            }
            params.month = monthIndex + 1;
            params.day =
                monthIndex === 0 ? yearDay : yearDay - DAYS_IN_YEAR[monthIndex - 1];
        }

        cascadeOverflow(params);
        params.hasTime = hasTimeComponent(params);

        return new PyRelativeDelta(params);
    }

    /**
     * @param {PyDateTime|PyDate} date
     * @param {PyRelativeDelta} delta
     * @returns {PyDateTime|PyDate}
     */
    static add(date, delta) {
        if (!(date instanceof PyDate || date instanceof PyDateTime)) {
            throw new NotSupportedError(
                "relativedelta can only be added to a date or a datetime",
            );
        }

        let year = (delta.year ?? date.year) + delta.years;
        let month = (delta.month ?? date.month) + delta.months;
        if (month < 1 || month > 12) {
            divmod(month - 1, 12, (carry, m) => {
                year += carry;
                month = m + 1;
            });
        }
        const day = Math.min(delta.day ?? date.day, daysInMonth(year, month));
        const s = tmxxx(
            year,
            month,
            day,
            delta.hour ?? /** @type {any} */ (date).hour ?? 0,
            delta.minute ?? /** @type {any} */ (date).minute ?? 0,
            delta.second ?? /** @type {any} */ (date).second ?? 0,
            delta.microsecond ?? /** @type {any} */ (date).microsecond ?? 0,
        );

        const newDateTime = new PyDateTime(
            s.year,
            s.month,
            s.day,
            s.hour,
            s.minute,
            s.second,
            s.microsecond,
        );

        let leapDays = 0;
        if (delta.leapDays && newDateTime.month > 2 && isLeap(newDateTime.year)) {
            leapDays = delta.leapDays;
        }

        const temp = newDateTime.add(
            PyTimeDelta.create({
                days: delta.days + leapDays,
                hours: delta.hours,
                minutes: delta.minutes,
                seconds: delta.seconds,
                microseconds: delta.microseconds,
            }),
        );

        const returnDate =
            !delta.hasTime && date instanceof PyDate
                ? new PyDate(temp.year, temp.month, temp.day)
                : temp;

        if (delta.weekday !== null) {
            const wantedDow = delta.weekday + 1;
            const jsDow =
                ymd2ord(returnDate.year, returnDate.month, returnDate.day) % 7;
            const days = (7 - jsDow + wantedDow) % 7;
            return returnDate.add(new PyTimeDelta(days, 0, 0));
        }
        return returnDate;
    }

    /**
     * @param {PyDateTime|PyDate} date
     * @param {PyRelativeDelta} delta
     * @returns {PyDateTime|PyDate}
     */
    static subtract(date, delta) {
        return PyRelativeDelta.add(date, delta.negate());
    }

    /**
     * @param {Record<string, any>} params
     * @param {1|-1} sign
     */
    constructor(params = {}, sign = +1) {
        this.years = sign * params.years;
        this.months = sign * params.months;
        this.days = sign * params.days;
        this.hours = sign * params.hours;
        this.minutes = sign * params.minutes;
        this.seconds = sign * params.seconds;
        this.microseconds = sign * params.microseconds;

        this.leapDays = params.leapDays || 0;
        this.hasTime = Boolean(params.hasTime);

        this.year = params.year;
        this.month = params.month;
        this.day = params.day;
        this.hour = params.hour;
        this.minute = params.minute;
        this.second = params.second;
        this.microsecond = params.microsecond;

        this.weekday = params.weekday;
    }

    /** @returns {PyRelativeDelta} */
    negate() {
        return new PyRelativeDelta(this, -1);
    }

    /**
     * @returns {boolean}
     */
    isTrue() {
        return Boolean(
            this.years ||
            this.months ||
            this.days ||
            this.hours ||
            this.minutes ||
            this.seconds ||
            this.microseconds ||
            this.leapDays ||
            this.year != null ||
            this.month != null ||
            this.day != null ||
            this.hour != null ||
            this.minute != null ||
            this.second != null ||
            this.microsecond != null ||
            this.weekday != null,
        );
    }

    /**
     * Field-by-field, like ``dateutil``'s own ``__eq__``. ``create()`` has
     * already folded ``weeks`` into ``days`` and cascaded every overflow, so
     * two deltas that mean the same thing carry the same fields.
     *
     * @param {any} other
     * @returns {boolean}
     */
    isEqual(other) {
        if (!(other instanceof PyRelativeDelta)) {
            return false;
        }
        return RELATIVE_DELTA_FIELDS.every(
            (field) =>
                /** @type {any} */ (this)[field] === /** @type {any} */ (other)[field],
        );
    }
}

/** @type {string[]} */
const RELATIVE_DELTA_FIELDS = [
    "years",
    "months",
    "days",
    "hours",
    "minutes",
    "seconds",
    "microseconds",
    "leapDays",
    "year",
    "month",
    "day",
    "hour",
    "minute",
    "second",
    "microsecond",
    "weekday",
];
