// @ts-check
/** @odoo-module native */

/** @module @web/core/py_js/py_date - Python date, datetime, time, and relativedelta emulation in JavaScript */

import { DateTime } from "@web/core/l10n/luxon";

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

export { PyTimeDelta } from "./py_timedelta.js";

export class NotSupportedError extends Error {}

/**
 * Shared strftime implementation. Only the conversion chars present in
 * ``converters`` are supported; any other ``%X`` raises ``ValueError``.
 *
 * @param {string} format
 * @param {Record<string, () => string>} converters conversion char → getter
 * @returns {string}
 */
/**
 * The locale-defined composites, in their C-locale form (what CPython's
 * ``strftime`` produces by default). They are expanded into the primitive
 * directives rather than implemented per class, because ``%c`` spans both the
 * date and the time halves, which live in different converter maps.
 */
const COMPOSITE_DIRECTIVES = {
    c: "%a %b %e %H:%M:%S %Y",
    x: "%m/%d/%y",
    X: "%H:%M:%S",
};

const DIRECTIVE_RE = /%(%|[A-Za-z])/g;

function strftime(format, converters) {
    // One expansion pass, sharing the regex so an escaped ``%%c`` stays a
    // literal "%" followed by "c". The expansions hold no composites of their
    // own, so a single pass reaches a fixed point.
    const expanded = format.replace(DIRECTIVE_RE, (m, c) =>
        c in COMPOSITE_DIRECTIVES
            ? /** @type {Record<string, string>} */ (COMPOSITE_DIRECTIVES)[c]
            : m,
    );
    return expanded.replace(DIRECTIVE_RE, (m, c) => {
        if (c === "%") {
            return "%";
        }
        if (c in converters) {
            return converters[c]();
        }
        throw new ValueError(`No known conversion for ${m}`);
    });
}

/**
 * ``%I`` 12-hour clock hour (01–12); midnight and noon both format as 12.
 * @param {number} hour24
 * @returns {string}
 */
function fmt12(hour24) {
    const h = hour24 % 12;
    return fmt2(h === 0 ? 12 : h);
}

/**
 * ``%p`` AM/PM marker (CPython's default C locale).
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
 * The date-derived strftime conversions, shared by all three date classes
 * (PyTime formats against 1900-01-01, as CPython's ``time.strftime`` does).
 *
 * Day and month names are the C-locale English ones, as are the ``%c``/``%x``/
 * ``%X`` composites expanded in {@link strftime}. CPython takes all of these
 * from the process locale, so a server running under a non-English ``LANG``
 * would render them differently. That residual mismatch is still the better
 * trade: these directives produce prose, nothing a domain compares on, and the
 * alternative — raising — takes down the whole expression, and with it the view
 * that evaluates it.
 *
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
    if (year < 1 || year > 9999) {
        // Python's MINYEAR..MAXYEAR. Unchecked, a negative year reached
        // ``fmt4`` and rendered as "00-5-01-01" — the malformed-date case this
        // function exists to stop, one field further left.
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
 * Range-validate the time components, mirroring Python's ``time()`` /
 * ``datetime()``.
 *
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
     * The current date in the USER's timezone. The client's zone is luxon's
     * ``Settings.defaultZone``, set from ``res.users.tz`` at boot (services/
     * user.js), so this matches the server's ``fields.Date.context_today``
     * (also the user tz) — not the browser zone, which ``new Date()`` would
     * give. Date fields are timezone-naive, so a ``date_field >= today`` domain
     * must use the user-perceived today; ``PyDateTime.now`` stays UTC.
     * ``context_today()`` (py_builtin.js) aliases this.
     *
     * @returns {PyDate}
     */
    static today() {
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
        this.year = year;
        this.month = month;
        this.day = day;
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
     * CPython's ``date.replace``: a copy with the given components substituted.
     * Goes through {@link PyDate.create} so an out-of-range result is rejected
     * the same way ``date(2024, 2, 30)`` is.
     *
     * @param  {...any} args
     * @returns {PyDate}
     */
    replace(...args) {
        const p = bindArgs(args, ["year", "month", "day"]);
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
            // CPython's ``date.__sub__`` is ``self + timedelta(-other.days)``:
            // it drops the sub-day part *before* negating. Negating the whole
            // duration first would borrow a day out of it (a -1µs delta
            // normalizes to days=-1), shifting the result by one day.
            return this.add(new PyTimeDelta(-other.days, 0, 0));
        }
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
     * CPython's ``datetime.replace``.
     *
     * @param  {...any} args
     * @returns {PyDateTime}
     */
    replace(...args) {
        const p = bindArgs(args, [
            "year",
            "month",
            "day",
            "hour",
            "minute",
            "second",
            "microsecond",
        ]);
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
        throw new NotSupportedError();
    }

    /** @returns {number} */
    toordinal() {
        return ymd2ord(this.year, this.month, this.day);
    }

    /**
     * Odoo's datetime wire format, which has no sub-second field — this is what
     * gets embedded in a domain, so it must stay second-resolution.
     * @returns {string}
     */
    toJSON() {
        return this.strftime("%Y-%m-%d %H:%M:%S");
    }

    /**
     * String representation used by ``str()`` / JS coercion. CPython's
     * ``str(datetime)`` appends ``.ffffff`` when the microsecond is non-zero;
     * deferring to {@link toJSON} instead silently dropped it.
     * @returns {string}
     */
    toString() {
        const base = this.strftime("%Y-%m-%d %H:%M:%S");
        return this.microsecond ? `${base}.${this.strftime("%f")}` : base;
    }

    /**
     * Reinterpret this naive wall-clock datetime as being in the USER's
     * timezone and convert it to UTC.
     *
     * The zone has to be the user's (luxon's ``Settings.defaultZone``, set from
     * ``res.users.tz`` at boot), because that is the zone the value being
     * converted came from — ``to_utc()`` exists to turn a ``context_today()``
     * wall clock into something comparable with a stored UTC datetime, and
     * {@link PyDate#today} reads the user zone. Going through ``new Date`` +
     * ``getTimezoneOffset`` instead took the offset from the BROWSER zone, so a
     * user whose Odoo tz differed from their machine's got a window shifted by
     * the difference between the two.
     *
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
     * A Python ``time`` carries no date, but this class extends PyDate and so
     * has to pass one up. It is 1900-01-01 — CPython's own reference date for
     * ``time.strftime``, which is what {@link PyTime#strftime} formats against.
     * Stamping *today* instead made every PyTime carry a hidden dependency on
     * the wall clock, so two times built either side of midnight differed in
     * fields nothing is allowed to read.
     *
     * @param {number} hour
     * @param {number} minute
     * @param {number} second
     */
    constructor(hour, minute, second) {
        super(1900, 1, 1);
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
     * CPython's ``time.replace`` — hour/minute/second, not the inherited
     * year/month/day of {@link PyDate#replace}.
     *
     * @param  {...any} args
     * @returns {PyTime}
     */
    replace(...args) {
        const p = bindArgs(args, ["hour", "minute", "second"]);
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
 * dateutil's ``relativedelta._fix`` cascade: each relative unit that overflows
 * its range carries into the next coarser one, truncating toward zero so the
 * sign survives. This never changes the delta a date sees — the relative units
 * are summed on application — but it is what decides {@link hasTimeComponent},
 * which is why it has to run: ``relativedelta(hours=24)`` is a pure-date delta
 * in dateutil, ``relativedelta(hours=1)`` is not.
 *
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
 * dateutil's ``relativedelta._has_time``, evaluated after {@link
 * cascadeOverflow}: whether the delta says anything about the time of day. It
 * decides the *type* of ``date + delta`` — dateutil promotes a date to a
 * datetime only for a time-bearing delta, and a plain date otherwise drops the
 * sub-day part of the result (``date.__add__`` reads only ``timedelta.days``).
 *
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

const argsSpec = ["dt1", "dt2"];
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
        // A month or year has no fixed length, so dateutil refuses a fractional
        // one instead of guessing. Without this the value flowed into
        // ``daysInMonth(year, 2.5)`` -> undefined and produced a NaN date.
        for (const key of ["years", "months"]) {
            if (!Number.isInteger(params[key])) {
                throw new ValueError(
                    "Non-integer years and months are ambiguous and not currently supported.",
                );
            }
        }
        if (params.weekday !== null) {
            // dateutil indexes a 7-tuple of weekday constants, so a negative
            // index counts back from Sunday (``weekday=-1`` is SU) and anything
            // outside -7..6 is an IndexError there.
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
            throw new NotSupportedError();
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
     * Truthiness matching dateutil's ``relativedelta.__bool__``: false only
     * when every relative field is zero and every absolute field is unset
     * (``bool(relativedelta())`` is ``False``). Without this the generic
     * ``Object.keys(value).length`` fallback made every relativedelta truthy,
     * so e.g. ``not relativedelta(days=n)`` was wrongly always-false at n=0.
     *
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
     * @param {PyRelativeDelta} other
     */
    isEqual(other) {
        throw new NotSupportedError();
    }
}
