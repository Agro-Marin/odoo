// @ts-check
/** @odoo-module native */

class AssertionError extends Error {}
export class ValueError extends Error {}

class OverflowError extends Error {}

/**
 * @param {number} year
 */
export function assertYearInRange(year) {
    if (year < 1 || year > 9999) {
        throw new OverflowError("date value out of range");
    }
}

/** @param {number} n */
export function fmt2(n) {
    return String(n).padStart(2, "0");
}

/** @param {number} n */
export function fmt4(n) {
    return String(n).padStart(4, "0");
}

/**
 * @template T
 * @param {number} a
 * @param {number} b
 * @param {(quotient: number, remainder: number) => T} fn
 * @returns {T}
 */
export function divmod(a, b, fn) {
    let mod = a % b;
    if ((mod > 0 && b < 0) || (mod < 0 && b > 0)) {
        mod += b;
    }
    return fn(Math.floor(a / b), mod);
}

/**
 * @param {boolean} bool
 * @param {string} [message]
 */
export function assert(bool, message = "AssertionError") {
    if (!bool) {
        throw new AssertionError(message);
    }
}

/** @type {(number | null)[]} */
const DAYS_IN_MONTH = [null, 31, 28, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31];

/** @type {(number | null)[]} */
const DAYS_BEFORE_MONTH = [null];
for (let dbm = 0, i = 1; i < DAYS_IN_MONTH.length; ++i) {
    DAYS_BEFORE_MONTH.push(dbm);
    dbm += /** @type {number} */ (DAYS_IN_MONTH[i]);
}

/**
 * @param {number} year
 * @param {number} month
 * @returns {number}
 */
export function daysInMonth(year, month) {
    if (month === 2 && isLeap(year)) {
        return 29;
    }
    return /** @type {number} */ (DAYS_IN_MONTH[month]);
}

/** @param {number} year */
export function isLeap(year) {
    return year % 4 === 0 && (year % 100 !== 0 || year % 400 === 0);
}

/** @param {number} year */
function daysBeforeYear(year) {
    const y = year - 1;
    return y * 365 + Math.floor(y / 4) - Math.floor(y / 100) + Math.floor(y / 400);
}

/**
 * @param {number} year
 * @param {number} month
 */
function daysBeforeMonth(year, month) {
    const postLeapFeb = month > 2 && isLeap(year);
    return /** @type {number} */ (DAYS_BEFORE_MONTH[month]) + (postLeapFeb ? 1 : 0);
}

/**
 * @param {number} year
 * @param {number} month
 * @param {number} day
 * @returns {number}
 */
export function ymd2ord(year, month, day) {
    const dim = daysInMonth(year, month);
    if (!(1 <= day && day <= dim)) {
        throw new ValueError(`day must be in 1..${dim}`);
    }
    return daysBeforeYear(year) + daysBeforeMonth(year, month) + day;
}

const DI400Y = daysBeforeYear(401);
const DI100Y = daysBeforeYear(101);
const DI4Y = daysBeforeYear(5);

/**
 * @param {number} n
 * @returns {{ year: number, month: number, day: number }}
 */
function ord2ymd(n) {
    --n;
    let n400 = 0,
        n100 = 0,
        n4 = 0,
        n1 = 0,
        n0 = 0;
    divmod(n, DI400Y, function (_n400, n) {
        n400 = _n400;
        divmod(n, DI100Y, function (_n100, n) {
            n100 = _n100;
            divmod(n, DI4Y, function (_n4, n) {
                n4 = _n4;
                divmod(n, 365, function (_n1, n) {
                    n1 = _n1;
                    n0 = n;
                });
            });
        });
    });

    n = n0;
    const year = n400 * 400 + 1 + n100 * 100 + n4 * 4 + n1;
    if (n1 === 4 || n100 === 4) {
        assert(n0 === 0);
        return {
            year: year - 1,
            month: 12,
            day: 31,
        };
    }

    const leapyear = n1 === 3 && (n4 !== 24 || n100 === 3);
    assert(leapyear === isLeap(year));
    let month = (n + 50) >> 5;
    let preceding =
        /** @type {number} */ (DAYS_BEFORE_MONTH[month]) +
        (month > 2 && leapyear ? 1 : 0);
    if (preceding > n) {
        --month;
        preceding -=
            /** @type {number} */ (DAYS_IN_MONTH[month]) +
            (month === 2 && leapyear ? 1 : 0);
    }
    n -= preceding;
    return {
        year: year,
        month: month,
        day: n + 1,
    };
}

/**
 * @param {number} year
 * @param {number} month
 * @param {number} day
 * @param {number} [hour]
 * @param {number} [minute]
 * @param {number} [second]
 * @param {number} [microsecond]
 * @returns {{ year: number, month: number, day: number, hour: number, minute: number, second: number, microsecond: number }}
 */
export function tmxxx(year, month, day, hour, minute, second, microsecond) {
    hour = hour || 0;
    minute = minute || 0;
    second = second || 0;
    microsecond = microsecond || 0;

    if (microsecond < 0 || microsecond > 999999) {
        divmod(microsecond, 1000000, function (carry, ms) {
            microsecond = ms;
            second = /** @type {number} */ (second) + carry;
        });
    }
    if (second < 0 || second > 59) {
        divmod(second, 60, function (carry, s) {
            second = s;
            minute = /** @type {number} */ (minute) + carry;
        });
    }
    if (minute < 0 || minute > 59) {
        divmod(minute, 60, function (carry, m) {
            minute = m;
            hour = /** @type {number} */ (hour) + carry;
        });
    }
    if (hour < 0 || hour > 23) {
        divmod(hour, 24, function (carry, h) {
            hour = h;
            day += carry;
        });
    }
    if (month < 1 || month > 12) {
        divmod(month - 1, 12, function (carry, m) {
            month = m + 1;
            year += carry;
        });
    }
    const dim = daysInMonth(year, month);
    if (day < 1 || day > dim) {
        if (day === 0) {
            --month;
            if (month > 0) {
                day = daysInMonth(year, month);
            } else {
                --year;
                month = 12;
                day = 31;
            }
        } else if (day === dim + 1) {
            ++month;
            day = 1;
            if (month > 12) {
                month = 1;
                ++year;
            }
        } else {
            const r = ord2ymd(ymd2ord(year, month, 1) + (day - 1));
            year = r.year;
            month = r.month;
            day = r.day;
        }
    }
    return {
        year: year,
        month: month,
        day: day,
        hour: hour,
        minute: minute,
        second: second,
        microsecond: microsecond,
    };
}
