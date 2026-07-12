// @ts-check
/** @odoo-module native */

/** @module @web/core/py_js/py_date - Python date, datetime, time, and relativedelta emulation in JavaScript */

import { bindArgs } from "./py_args.js";
import {
    assert,
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

// Re-export for backward compatibility
export { PyTimeDelta } from "./py_timedelta.js";

// ─── Errors ──────────────────────────────────────────────────────────────────

export class NotSupportedError extends Error {}

// ─── strftime ──────────────────────────────────────────────────────────────────

/**
 * Shared strftime implementation. Only the conversion chars present in
 * ``converters`` are supported; any other ``%X`` raises ``ValueError``.
 *
 * @param {string} format
 * @param {Record<string, () => string>} converters conversion char → getter
 * @returns {string}
 */
function strftime(format, converters) {
    return format.replace(/%(%|[A-Za-z])/g, (m, c) => {
        if (c === "%") {
            // ``%%`` is a literal percent sign.
            return "%";
        }
        if (c in converters) {
            return converters[c]();
        }
        throw new ValueError(`No known conversion for ${m}`);
    });
}

// ─── construction validation ─────────────────────────────────────────────────

/**
 * Reject a non-integer component (also catching the missing-argument case,
 * where the value is ``undefined``). Mirrors Python's TypeError for
 * ``date(2020, 1)`` and ``date(2020, "x", 1)``.
 *
 * @param {string} name
 * @param {any} value
 */
function assertIntComponent(name, value) {
    if (typeof value !== "number" || !Number.isInteger(value)) {
        throw new ValueError(`${name} must be an integer`);
    }
}

/**
 * Range-validate the date components, mirroring Python's ``date()`` (which
 * raises ``ValueError`` on ``date(2020, 13, 45)``). Without this the raw
 * values flowed straight into strftime, yielding garbage like "2020-13-45"
 * or "2020-01-undefined".
 *
 * @param {any} year
 * @param {any} month
 * @param {any} day
 */
function assertDateComponents(year, month, day) {
    assertIntComponent("year", year);
    assertIntComponent("month", month);
    assertIntComponent("day", day);
    if (month < 1 || month > 12) {
        throw new ValueError("month must be in 1..12");
    }
    if (day < 1 || day > daysInMonth(year, month)) {
        throw new ValueError("day is out of range for month");
    }
}

/**
 * Range-validate the time components, mirroring Python's ``time()`` /
 * ``datetime()``.
 *
 * @param {any} hour
 * @param {any} minute
 * @param {any} second
 * @param {any} [microsecond=0]
 */
function assertTimeComponents(hour, minute, second, microsecond = 0) {
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

// ─── PyDate ──────────────────────────────────────────────────────────────────

export class PyDate {
    /**
     * The current date in the USER's timezone. Date fields are timezone-
     * naive (stored/shipped as-is), so a ``date_field >= today`` domain
     * must use the user-perceived today — unlike ``PyDateTime.now``, which
     * is UTC. ``context_today()`` (py_builtin.js) aliases this.
     *
     * @returns {PyDate}
     */
    static today() {
        const d = new Date();
        return new PyDate(d.getFullYear(), d.getMonth() + 1, d.getDate());
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
        this.year = year;
        this.month = month; // 1-indexed => 1 = january, 2 = february, ...
        this.day = day; // 1-indexed => 1 = first day of month, ...
    }

    /**
     * @param  {...any} args
     * @returns {PyDate}
     */
    static create(...args) {
        const { year, month, day } = bindArgs(args, ["year", "month", "day"]);
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
        // PyTime extends PyDate (it stamps "today" as its date part), so an
        // exact-kind guard is needed: Python date == time is always False.
        if (!(other instanceof PyDate) || other instanceof PyTime) {
            return false;
        }
        return (
            this.year === other.year &&
            this.month === other.month &&
            this.day === other.day
        );
    }

    /**
     * @param {string} format
     * @returns {string}
     */
    strftime(format) {
        return strftime(format, {
            Y: () => fmt4(this.year),
            m: () => fmt2(this.month),
            d: () => fmt2(this.day),
        });
    }

    /**
     * @param {PyTimeDelta | PyDate} other
     * @returns {PyDate | PyTimeDelta}
     */
    subtract(other) {
        if (other instanceof PyTimeDelta) {
            return this.add(other.negate());
        }
        // Exact-kind guard: PyTime extends PyDate, and date - time is a
        // TypeError in Python (the inherited date branch would return a
        // nonsense timedelta based on the time's stamped "today").
        if (other instanceof PyDate && !(other instanceof PyTime)) {
            return PyTimeDelta.create(this.toordinal() - other.toordinal());
        }
        throw new NotSupportedError();
    }

    /** @returns {string} */
    toJSON() {
        return this.strftime("%Y-%m-%d");
    }

    /**
     * String representation used by ``str()`` / JS coercion. Subclasses
     * (PyDateTime, PyTime) override ``toJSON`` so this stays correct for them.
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
     * Ordering protocol: relational operators (``<``, ``>``) coerce via
     * ToPrimitive → ``valueOf``. Returning the ordinal makes dates compare
     * chronologically; equality still goes through ``isEqual``.
     *
     * @returns {number}
     */
    valueOf() {
        return this.toordinal();
    }
}

// ─── PyDateTime ──────────────────────────────────────────────────────────────

/** Proleptic Gregorian ordinal of 1970-01-01, i.e. ``ymd2ord(1970, 1, 1)``. */
const UNIX_EPOCH_ORDINAL = 719163;

export class PyDateTime {
    /**
     * The current datetime in UTC — matches how the SERVER evaluates
     * ``datetime.now()`` in domains/modifiers, directly comparable to UTC
     * datetime record values. Using LOCAL now made ``deadline < now``-style
     * checks drift by the user's UTC offset.
     *
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
     * @param  {...any} args
     * @returns {PyDateTime}
     */
    static create(...args) {
        const namedArgs = bindArgs(args, [
            "year",
            "month",
            "day",
            "hour",
            "minute",
            "second",
            "microsecond",
        ]);
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
     * @param  {...any} args
     * @returns {PyDateTime}
     */
    static combine(...args) {
        const { date, time } = bindArgs(args, ["date", "time"]);
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
     * @param {string} format
     * @returns {string}
     */
    strftime(format) {
        return strftime(format, {
            Y: () => fmt4(this.year),
            m: () => fmt2(this.month),
            d: () => fmt2(this.day),
            H: () => fmt2(this.hour),
            M: () => fmt2(this.minute),
            S: () => fmt2(this.second),
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
        throw new NotSupportedError();
    }

    /** @returns {number} */
    toordinal() {
        return ymd2ord(this.year, this.month, this.day);
    }

    /** @returns {string} */
    toJSON() {
        return this.strftime("%Y-%m-%d %H:%M:%S");
    }

    /**
     * String representation used by ``str()`` / JS coercion.
     * @returns {string}
     */
    toString() {
        return this.toJSON();
    }

    /** @returns {PyDateTime} */
    to_utc() {
        const d = new Date(
            this.year,
            this.month - 1,
            this.day,
            this.hour,
            this.minute,
            this.second,
        );
        const timedelta = PyTimeDelta.create({
            minutes: d.getTimezoneOffset(),
        });
        return this.add(timedelta);
    }

    /**
     * Ordering protocol (see {@link PyDate#valueOf}): microseconds since the
     * Unix epoch, exact as an IEEE-754 double for years ~1685–2255.
     *
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

// ─── PyTime ──────────────────────────────────────────────────────────────────

export class PyTime extends PyDate {
    /**
     * @param  {...any} args
     * @returns {PyTime}
     */
    static create(...args) {
        const namedArgs = bindArgs(args, ["hour", "minute", "second"]);
        const hour = namedArgs.hour || 0;
        const minute = namedArgs.minute || 0;
        const second = namedArgs.second || 0;
        assertTimeComponents(hour, minute, second);
        return new PyTime(hour, minute, second);
    }

    /**
     * @param {number} hour
     * @param {number} minute
     * @param {number} second
     */
    constructor(hour, minute, second) {
        const now = new Date();
        const year = now.getFullYear();
        const month = now.getMonth() + 1;
        const day = now.getDate();
        super(year, month, day);
        this.hour = hour;
        this.minute = minute;
        this.second = second;
    }

    /**
     * Python's time supports no arithmetic at all (time ± timedelta and
     * time - time are TypeErrors); block the operations inherited from PyDate,
     * which would silently use the stamped "today" date part.
     *
     * @param {PyTimeDelta} [timedelta]
     * @returns {PyDate}
     */
    add(timedelta) {
        throw new NotSupportedError();
    }

    /**
     * @param {PyTimeDelta | PyDate} [other]
     * @returns {PyDate | PyTimeDelta}
     */
    subtract(other) {
        throw new NotSupportedError();
    }

    /**
     * @param {any} other
     * @returns {boolean}
     */
    isEqual(other) {
        // Overrides the inherited date-part comparison, which tied ALL times
        // created the same day and could equate a time with a plain date.
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
     * @param {string} format
     * @returns {string}
     */
    strftime(format) {
        return strftime(format, {
            Y: () => fmt4(this.year),
            m: () => fmt2(this.month),
            d: () => fmt2(this.day),
            H: () => fmt2(this.hour),
            M: () => fmt2(this.minute),
            S: () => fmt2(this.second),
        });
    }

    toJSON() {
        return this.strftime("%H:%M:%S");
    }

    /**
     * Ordering protocol (see {@link PyDate#valueOf}): seconds since midnight.
     * Overrides the inherited PyDate ordinal (which would compare the stamped
     * "today" date and tie all times) so times order by time of day. Equality
     * is untouched — it still goes through the inherited ``isEqual``.
     *
     * @returns {number}
     */
    valueOf() {
        return this.hour * 3600 + this.minute * 60 + this.second;
    }
}

// ─── PyRelativeDelta ─────────────────────────────────────────────────────────

/*
 * This list is intended to be of that shape (32 days in december), it is used by
 * the algorithm that computes "relativedelta yearday". The algorithm was adapted
 * from the one in python (https://github.com/dateutil/dateutil/blob/2.7.3/dateutil/relativedelta.py#L199)
 */
const DAYS_IN_YEAR = [31, 59, 90, 120, 151, 181, 212, 243, 273, 304, 334, 366];

/**
 * Valid ranges for the ABSOLUTE (singular) arguments, mirroring what
 * dateutil/CPython ultimately enforce when the delta is applied
 * (IllegalMonthError for month, ValueError from datetime.replace for the
 * others). Relative (plural) arguments are unbounded, negative included.
 */
const PERIOD_RANGES = {
    year: [1, 9999],
    month: [1, 12],
    // day has no upper bound: dateutil clamps any excess (day=31/45 both mean
    // "last day of the month"), and PyRelativeDelta.add clamps identically.
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

const argsSpec = ["dt1", "dt2"]; // all other arguments are kwargs
export class PyRelativeDelta {
    /**
     * @param  {...any} args
     * @returns {PyRelativeDelta}
     */
    static create(...args) {
        const params = bindArgs(args, argsSpec);
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
        params.days += 7 * params.weeks;
        // The public kwarg is spelled `leapdays` (dateutil); internally the
        // instance property is `leapDays` — bridge the two so the kwarg is
        // not silently dropped (the yearday path below may override it).
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
            for (let monthIndex = 0; monthIndex < DAYS_IN_YEAR.length; monthIndex++) {
                if (yearDay <= DAYS_IN_YEAR[monthIndex]) {
                    params.month = monthIndex + 1;
                    if (monthIndex === 0) {
                        params.day = yearDay;
                    } else {
                        params.day = yearDay - DAYS_IN_YEAR[monthIndex - 1];
                    }
                    break;
                }
            }
        }

        return new PyRelativeDelta(params);
    }

    /**
     * @param {PyDateTime|PyDate} date
     * @param {PyRelativeDelta} delta
     * @returns {PyDateTime|PyDate}
     */
    static add(date, delta) {
        if (!(date instanceof PyDate || date instanceof PyDateTime)) {
            throw new NotSupportedError();
        }

        // First pass: resolve target year/month, then clamp day to the
        // target month's length. dateutil semantics: a day past month-end
        // lands on the last day (2020-01-31 + months=1 → 2020-02-29, never
        // rolling over into 2020-03-02).
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

        // Second pass: apply day and time deltas
        const temp = newDateTime.add(
            PyTimeDelta.create({
                days: delta.days + leapDays,
                hours: delta.hours,
                minutes: delta.minutes,
                seconds: delta.seconds,
                microseconds: delta.microseconds,
            }),
        );

        // Determine return type from input type and actual time values.
        // dateutil normalizes the delta before checking `_has_time`, so
        // `relativedelta(hours=24)` carries into `days=1` and stays a date,
        // while `hours=5` promotes to datetime. For a date base (always
        // midnight) the normalized residual time equals the result's clock,
        // so testing the result's h/m/s/µs is equivalent to dateutil here.
        const hasTime = Boolean(
            temp.hour || temp.minute || temp.second || temp.microsecond,
        );
        const returnDate =
            !hasTime && date instanceof PyDate
                ? new PyDate(temp.year, temp.month, temp.day)
                : temp;

        // Final pass: target the wanted day of the week (if necessary)
        if (delta.weekday !== null) {
            const wantedDow = delta.weekday + 1; // python: Monday is 0 ; JS: Monday is 1;
            const _date = new Date(
                returnDate.year,
                returnDate.month - 1,
                returnDate.day,
            );
            const days = (7 - _date.getDay() + wantedDow) % 7;
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

        // dateutil's __neg__ deliberately does NOT negate leapdays — keep it
        // unsigned here (verified against dateutil's source).
        this.leapDays = params.leapDays || 0;

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
     * @param {PyRelativeDelta} other
     */
    isEqual(other) {
        // Normalization only happens on add/subtract, not in the
        // constructor, so isEqual can't be supported yet.
        throw new NotSupportedError();
    }
}
