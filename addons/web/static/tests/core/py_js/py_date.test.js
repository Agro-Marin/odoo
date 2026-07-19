// @ts-check

import { describe, expect, test } from "@odoo/hoot";
import { mockDate } from "@odoo/hoot-mock";
import { evaluateExpr } from "@web/core/py_js/py";
import { PyDate, PyDateTime, PyTimeDelta } from "@web/core/py_js/py_date";

const check = (expr, fn) => {
    const d0 = new Date();
    const result = evaluateExpr(expr);
    const d1 = new Date();
    return fn(d0) <= result && result <= fn(d1);
};

const format = (n) => String(n).padStart(2, "0");

// Date semantics under test (must match py_date.js / py_builtin.js):
//   - `today` / `date.today()` / `context_today()` → USER-LOCAL date (date
//     fields are timezone-naive; "today" is the user's today).
//   - `now` / `datetime.now()` / `time.strftime` → UTC (datetime fields are
//     UTC strings, so `datetime_field < now` must compare in UTC).
// Computing expectations with the matching getters keeps these green on any
// host timezone, not just UTC.
const formatDate = (d) => {
    const year = d.getFullYear();
    const month = format(d.getMonth() + 1);
    const day = format(d.getDate());
    return `${year}-${month}-${day}`;
};

const formatDateTimeUTC = (d) => {
    const year = d.getUTCFullYear();
    const month = format(d.getUTCMonth() + 1);
    const day = format(d.getUTCDate());
    const h = format(d.getUTCHours());
    const m = format(d.getUTCMinutes());
    const sec = format(d.getUTCSeconds());
    return `${year}-${month}-${day} ${h}:${m}:${sec}`;
};

describe.current.tags("headless");

describe("time", () => {
    test("strftime", () => {
        expect(check("time.strftime('%Y')", (d) => String(d.getUTCFullYear()))).toBe(
            true,
        );
        expect(
            check(
                "time.strftime('%Y') + '-01-30'",
                (d) => String(d.getFullYear()) + "-01-30",
            ),
        ).toBe(true);
        expect(check("time.strftime('%Y-%m-%d %H:%M:%S')", formatDateTimeUTC)).toBe(
            true,
        );
    });
});

describe("datetime.datetime", () => {
    test("datetime.datetime.now", () => {
        expect(check("datetime.datetime.now().year", (d) => d.getUTCFullYear())).toBe(
            true,
        );
        expect(check("datetime.datetime.now().month", (d) => d.getUTCMonth() + 1)).toBe(
            true,
        );
        expect(check("datetime.datetime.now().day", (d) => d.getUTCDate())).toBe(true);
        expect(check("datetime.datetime.now().hour", (d) => d.getUTCHours())).toBe(
            true,
        );
        expect(check("datetime.datetime.now().minute", (d) => d.getUTCMinutes())).toBe(
            true,
        );
        expect(check("datetime.datetime.now().second", (d) => d.getUTCSeconds())).toBe(
            true,
        );
    });

    test("various operations", () => {
        const expr1 = "datetime.datetime(day=3,month=4,year=2001).strftime('%Y-%m-%d')";
        expect(evaluateExpr(expr1)).toBe("2001-04-03");
        const expr2 = "datetime.datetime(2001, 4, 3).strftime('%Y-%m-%d')";
        expect(evaluateExpr(expr2)).toBe("2001-04-03");
        const expr3 =
            "datetime.datetime(day=3,month=4,second=12, year=2001,minute=32).strftime('%Y-%m-%d %H:%M:%S')";
        expect(evaluateExpr(expr3)).toBe("2001-04-03 00:32:12");
    });

    test("to_utc", () => {
        mockDate("2021-09-17 10:00:00", +6);

        const expr =
            "datetime.datetime.combine(context_today(), datetime.time(0,0,0)).to_utc()";

        expect(JSON.stringify(evaluateExpr(expr))).toBe(`"2021-09-16 18:00:00"`);
    });

    test("to_utc in october with winter/summer change", () => {
        mockDate("2021-10-17 10:00:00", "Europe/Brussels");

        const expr = "datetime.datetime(2022, 10, 17).to_utc()";
        expect(JSON.stringify(evaluateExpr(expr))).toBe(`"2022-10-16 22:00:00"`);
    });

    test("datetime.datetime.combine", () => {
        const expr =
            "datetime.datetime.combine(context_today(), datetime.time(23,59,59)).strftime('%Y-%m-%d %H:%M:%S')";
        expect(check(expr, (d) => formatDate(d) + " 23:59:59")).toBe(true);
    });

    test("datetime.datetime.toJSON", () => {
        expect(
            JSON.stringify(
                evaluateExpr("datetime.datetime(day=3,month=4,year=2001,hour=10)"),
            ),
        ).toBe(`"2001-04-03 10:00:00"`);
    });

    test("datetime + timedelta", function () {
        expect.assertions(6);

        expect(
            evaluateExpr(
                "(datetime.datetime(2017, 2, 15, 1, 7, 31) + datetime.timedelta(days=1)).strftime('%Y-%m-%d %H:%M:%S')",
            ),
        ).toBe("2017-02-16 01:07:31");
        expect(
            evaluateExpr(
                "(datetime.datetime(2012, 2, 15, 1, 7, 31) - datetime.timedelta(hours=1)).strftime('%Y-%m-%d %H:%M:%S')",
            ),
        ).toBe("2012-02-15 00:07:31");
        expect(
            evaluateExpr(
                "(datetime.datetime(2012, 2, 15, 1, 7, 31) + datetime.timedelta(hours=-1)).strftime('%Y-%m-%d %H:%M:%S')",
            ),
        ).toBe("2012-02-15 00:07:31");
        expect(
            evaluateExpr(
                "(datetime.datetime(2012, 2, 15, 1, 7, 31) + datetime.timedelta(minutes=100)).strftime('%Y-%m-%d %H:%M:%S')",
            ),
        ).toBe("2012-02-15 02:47:31");
        expect(
            evaluateExpr(
                "(datetime.date(day=3,month=4,year=2001) + datetime.timedelta(days=-1)).strftime('%Y-%m-%d')",
            ),
        ).toBe("2001-04-02");
        expect(
            evaluateExpr(
                "(datetime.timedelta(days=-1) + datetime.date(day=3,month=4,year=2001)).strftime('%Y-%m-%d')",
            ),
        ).toBe("2001-04-02");
    });
});

describe("datetime.date", () => {
    test("datetime.date.today", () => {
        expect(check("(datetime.date.today()).strftime('%Y-%m-%d')", formatDate)).toBe(
            true,
        );
    });

    test("various operations", () => {
        const expr1 = "datetime.date(day=3,month=4,year=2001).strftime('%Y-%m-%d')";
        expect(evaluateExpr(expr1)).toBe("2001-04-03");
        const expr2 = "datetime.date(2001, 4, 3).strftime('%Y-%m-%d')";
        expect(evaluateExpr(expr2)).toBe("2001-04-03");
    });

    test("strftime renders time directives as midnight (CPython parity)", () => {
        // A datetime format string applied to a bare date must not throw — the
        // server-side Python evaluation renders the time part as midnight, so
        // the client must agree (a copy-pasted "%Y-%m-%d %H:%M:%S" is common).
        expect(
            evaluateExpr("datetime.date(2024,3,5).strftime('%Y-%m-%d %H:%M:%S')"),
        ).toBe("2024-03-05 00:00:00");
        expect(evaluateExpr("datetime.date(2024,3,5).strftime('%I %p')")).toBe("12 AM");
    });

    test("datetime.date.toJSON", () => {
        expect(
            JSON.stringify(evaluateExpr("datetime.date(year=1997,month=5,day=18)")),
        ).toBe(`"1997-05-18"`);
    });

    test("basic operations with dates", function () {
        expect.assertions(19);

        let ctx = {
            d1: PyDate.create(2002, 1, 31),
            d2: PyDate.create(1956, 1, 31),
        };

        expect(evaluateExpr("(d1 - d2).days", ctx)).toBe(46 * 365 + 12);
        expect(evaluateExpr("(d1 - d2).seconds", ctx)).toBe(0);
        expect(evaluateExpr("(d1 - d2).microseconds", ctx)).toBe(0);

        ctx = {
            a: PyDate.create(2002, 3, 2),
            day: PyTimeDelta.create({ days: 1 }),
            week: PyTimeDelta.create({ days: 7 }),
            date: PyDate,
        };

        expect(evaluateExpr("a + day == date(2002, 3, 3)", ctx)).toBe(true);
        expect(evaluateExpr("day + a == date(2002, 3, 3)", ctx)).toBe(true); // 5
        expect(evaluateExpr("a - day == date(2002, 3, 1)", ctx)).toBe(true);
        expect(evaluateExpr("-day + a == date(2002, 3, 1)", ctx)).toBe(true);
        expect(evaluateExpr("a + week == date(2002, 3, 9)", ctx)).toBe(true);
        expect(evaluateExpr("a - week == date(2002, 2, 23)", ctx)).toBe(true);
        expect(evaluateExpr("a + 52*week == date(2003, 3, 1)", ctx)).toBe(true); // 10
        expect(evaluateExpr("a - 52*week == date(2001, 3, 3)", ctx)).toBe(true);
        expect(evaluateExpr("(a + week) - a == week", ctx)).toBe(true);
        expect(evaluateExpr("(a + day) - a == day", ctx)).toBe(true);
        expect(evaluateExpr("(a - week) - a == -week", ctx)).toBe(true);
        expect(evaluateExpr("(a - day) - a == -day", ctx)).toBe(true); // 15
        expect(evaluateExpr("a - (a + week) == -week", ctx)).toBe(true);
        expect(evaluateExpr("a - (a + day) == -day", ctx)).toBe(true);
        expect(evaluateExpr("a - (a - week) == week", ctx)).toBe(true);
        expect(evaluateExpr("a - (a - day) == day", ctx)).toBe(true);

        // expect(() => evaluateExpr("a + 1", ctx)).toThrow(/^Error: TypeError:/); //20
        // expect(() => evaluateExpr("a - 1", ctx)).toThrow(/^Error: TypeError:/);
        // expect(() => evaluateExpr("1 + a", ctx)).toThrow(/^Error: TypeError:/);
        // expect(() => evaluateExpr("1 - a", ctx)).toThrow(/^Error: TypeError:/);

        // // delta - date is senseless.
        // expect(() => evaluateExpr("day - a", ctx)).toThrow(/^Error: TypeError:/);

        // // mixing date and (delta or date) via * or // is senseless
        // expect(() => evaluateExpr("day * a", ctx)).toThrow(/^Error: TypeError:/); // 25
        // expect(() => evaluateExpr("a * day", ctx)).toThrow(/^Error: TypeError:/);
        // expect(() => evaluateExpr("day // a", ctx)).toThrow(/^Error: TypeError:/);
        // expect(() => evaluateExpr("a // day", ctx)).toThrow(/^Error: TypeError:/);
        // expect(() => evaluateExpr("a * a", ctx)).toThrow(/^Error: TypeError:/);
        // expect(() => evaluateExpr("a // a", ctx)).toThrow(/^Error: TypeError:/); // 30

        // // date + date is senseless
        // expect(() => evaluateExpr("a + a", ctx)).toThrow(/^Error: TypeError:/);
    });
});

describe("datetime.time", () => {
    test("various operations", () => {
        const expr1 = "datetime.time(hour=3,minute=2. second=1).strftime('%H:%M:%S')";
        expect(evaluateExpr(expr1)).toBe("03:02:01");
    });

    test("attributes", () => {
        const expr1 = "datetime.time(hour=3,minute=2. second=1).hour";
        expect(evaluateExpr(expr1)).toBe(3);
        const expr2 = "datetime.time(hour=3,minute=2. second=1).minute";
        expect(evaluateExpr(expr2)).toBe(2);
        const expr3 = "datetime.time(hour=3,minute=2. second=1).second";
        expect(evaluateExpr(expr3)).toBe(1);
    });

    test("datetime.time.toJSON", () => {
        expect(
            JSON.stringify(evaluateExpr("datetime.time(hour=11,minute=45,second=15)")),
        ).toBe(`"11:45:15"`);
    });

    test("strftime date directives use 1900-01-01, not the stamped today", () => {
        // CPython: a bare time has no date, so %Y/%m/%d format against the
        // default 1900-01-01 (the class instance internally stamps "today",
        // which previously leaked a run-dependent current year).
        expect(evaluateExpr("datetime.time(9,7,3).strftime('%Y-%m-%d')")).toBe(
            "1900-01-01",
        );
        // 12-hour clock + AM/PM.
        expect(evaluateExpr("datetime.time(0,7,3).strftime('%I:%M %p')")).toBe(
            "12:07 AM",
        );
        expect(evaluateExpr("datetime.time(13,7,3).strftime('%I:%M %p')")).toBe(
            "01:07 PM",
        );
    });

    test("time equality compares the time of day", () => {
        expect(evaluateExpr("datetime.time(1,0) == datetime.time(1,0)")).toBe(true);
        expect(evaluateExpr("datetime.time(1,0) == datetime.time(2,0)")).toBe(false);
        expect(evaluateExpr("datetime.time(1,0) == datetime.date(2020,1,1)")).toBe(
            false,
        );
    });

    test("time supports no arithmetic (Python TypeError)", () => {
        expect(() =>
            evaluateExpr("datetime.time(1,0) + datetime.timedelta(hours=1)"),
        ).toThrow();
        expect(() =>
            evaluateExpr("datetime.time(1,0) - datetime.timedelta(hours=1)"),
        ).toThrow();
        expect(() =>
            evaluateExpr("datetime.time(1,0) - datetime.time(0,30)"),
        ).toThrow();
        expect(() =>
            evaluateExpr("datetime.date(2020,1,1) - datetime.time(1,0)"),
        ).toThrow();
    });
});

describe("relativedelta relative : period is plural", () => {
    test("adding date and relative delta", () => {
        const expr1 =
            "(datetime.date(day=3,month=4,year=2001) + relativedelta(days=-1)).strftime('%Y-%m-%d')";
        expect(evaluateExpr(expr1)).toBe("2001-04-02");
        const expr2 =
            "(datetime.date(day=3,month=4,year=2001) + relativedelta(weeks=-1)).strftime('%Y-%m-%d')";
        expect(evaluateExpr(expr2)).toBe("2001-03-27");
    });

    test("adding relative delta and date", () => {
        const expr =
            "(relativedelta(days=-1) + datetime.date(day=3,month=4,year=2001)).strftime('%Y-%m-%d')";
        expect(evaluateExpr(expr)).toBe("2001-04-02");
    });

    test("date + delta type follows dateutil normalization (hours=24 stays date)", () => {
        // dateutil normalizes the delta before deciding the type: hours=24
        // carries into days=1 (no residual time) → stays a date, while a
        // sub-day residual (hours=5) promotes to datetime.
        const carried = evaluateExpr(
            "datetime.date(day=3,month=4,year=2001) + relativedelta(hours=24)",
        );
        expect(carried).toBeInstanceOf(PyDate);
        expect(carried).not.toBeInstanceOf(PyDateTime);
        expect(carried.strftime("%Y-%m-%d")).toBe("2001-04-04");

        const promoted = evaluateExpr(
            "datetime.date(day=3,month=4,year=2001) + relativedelta(hours=5)",
        );
        expect(promoted).toBeInstanceOf(PyDateTime);
        expect(promoted.strftime("%Y-%m-%d %H:%M:%S")).toBe("2001-04-03 05:00:00");
    });

    test("adding/subtracting relative delta and date -- shifts order of magnitude", () => {
        const expr =
            "(relativedelta(hours=14) + datetime.datetime(hour=15,day=3,month=4,year=2001)).strftime('%Y-%m-%d %H:%M:%S')";
        expect(evaluateExpr(expr)).toBe("2001-04-04 05:00:00");

        const expr2 =
            "(relativedelta(days=32) + datetime.date(day=3,month=4,year=2001)).strftime('%Y-%m-%d')";
        expect(evaluateExpr(expr2)).toBe("2001-05-05");

        const expr3 =
            "(relativedelta(months=14) + datetime.date(day=3,month=4,year=2001)).strftime('%Y-%m-%d')";
        expect(evaluateExpr(expr3)).toBe("2002-06-03");

        const expr4 =
            "(datetime.datetime(hour=13,day=3,month=4,year=2001) - relativedelta(hours=14)).strftime('%Y-%m-%d %H:%M:%S')";
        expect(evaluateExpr(expr4)).toBe("2001-04-02 23:00:00");

        const expr5 =
            "(datetime.date(day=3,month=4,year=2001) - relativedelta(days=4)).strftime('%Y-%m-%d')";
        expect(evaluateExpr(expr5)).toBe("2001-03-30");

        const expr6 =
            "(datetime.date(day=3,month=4,year=2001) - relativedelta(months=5)).strftime('%Y-%m-%d')";
        expect(evaluateExpr(expr6)).toBe("2000-11-03");
    });

    test("month/year arithmetic clamps to the end of the target month", () => {
        // dateutil parity: when the source day exceeds the target month's
        // length, the day is clamped to that month's last day — it must not
        // overflow into the following month.
        const expr1 =
            "(datetime.date(2020,1,31) + relativedelta(months=1)).strftime('%Y-%m-%d')";
        expect(evaluateExpr(expr1)).toBe("2020-02-29");

        const expr2 =
            "(datetime.date(2026,3,31) - relativedelta(months=1)).strftime('%Y-%m-%d')";
        expect(evaluateExpr(expr2)).toBe("2026-02-28");

        const expr3 =
            "(datetime.date(2020,2,29) + relativedelta(years=1)).strftime('%Y-%m-%d')";
        expect(evaluateExpr(expr3)).toBe("2021-02-28");

        const expr4 =
            "(datetime.date(2021,1,31) + relativedelta(months=1)).strftime('%Y-%m-%d')";
        expect(evaluateExpr(expr4)).toBe("2021-02-28");

        const expr5 =
            "(datetime.date(2021,3,31) + relativedelta(months=1)).strftime('%Y-%m-%d')";
        expect(evaluateExpr(expr5)).toBe("2021-04-30");

        const expr6 =
            "(datetime.datetime(2020,1,31,5,6,7) + relativedelta(months=1)).strftime('%Y-%m-%d %H:%M:%S')";
        expect(evaluateExpr(expr6)).toBe("2020-02-29 05:06:07");
    });

    test("day 29-31 round trip through a shorter month", () => {
        // Forward then back: days beyond the clamp are lost (dateutil parity).
        const expr1 =
            "(datetime.date(2020,1,29) + relativedelta(months=1) - relativedelta(months=1)).strftime('%Y-%m-%d')";
        expect(evaluateExpr(expr1)).toBe("2020-01-29");

        const expr2 =
            "(datetime.date(2020,1,30) + relativedelta(months=1) - relativedelta(months=1)).strftime('%Y-%m-%d')";
        expect(evaluateExpr(expr2)).toBe("2020-01-29");

        const expr3 =
            "(datetime.date(2020,1,31) + relativedelta(months=1) - relativedelta(months=1)).strftime('%Y-%m-%d')";
        expect(evaluateExpr(expr3)).toBe("2020-01-29");

        // Back then forward.
        const expr4 =
            "(datetime.date(2020,3,31) - relativedelta(months=1) + relativedelta(months=1)).strftime('%Y-%m-%d')";
        expect(evaluateExpr(expr4)).toBe("2020-03-29");

        const expr5 =
            "(datetime.date(2021,3,30) - relativedelta(months=1) + relativedelta(months=1)).strftime('%Y-%m-%d')";
        expect(evaluateExpr(expr5)).toBe("2021-03-28");
    });

    test("subtracting date and relative delta", () => {
        const expr1 =
            "(datetime.date(day=3,month=4,year=2001) - relativedelta(days=-1)).strftime('%Y-%m-%d')";
        expect(evaluateExpr(expr1)).toBe("2001-04-04");
        const expr2 =
            "(datetime.date(day=3,month=4,year=2001) - relativedelta(weeks=-1)).strftime('%Y-%m-%d')";
        expect(evaluateExpr(expr2)).toBe("2001-04-10");
        const expr3 =
            "(datetime.date(day=3,month=4,year=2001) - relativedelta(days=1)).strftime('%Y-%m-%d')";
        expect(evaluateExpr(expr3)).toBe("2001-04-02");
        const expr4 =
            "(datetime.date(day=3,month=4,year=2001) - relativedelta(weeks=1)).strftime('%Y-%m-%d')";
        expect(evaluateExpr(expr4)).toBe("2001-03-27");
    });
});

describe("relativedelta absolute : period is singular", () => {
    test("throws when period negative", () => {
        const expr1 = "relativedelta(day=-1)";
        expect(() => evaluateExpr(expr1)).toThrow("day -1 is out of range");

        const expr2 = "relativedelta(month=-1)";
        expect(() => evaluateExpr(expr2)).toThrow("month -1 is out of range");
    });

    test("throws when absolute period is out of its dateutil range", () => {
        // dateutil/CPython reject these when the delta is applied
        // (IllegalMonthError / ValueError from datetime.replace); the check
        // is made eagerly here instead of silently normalizing.
        expect(() => evaluateExpr("relativedelta(month=15)")).toThrow(
            "month 15 is out of range",
        );
        expect(() => evaluateExpr("relativedelta(month=0)")).toThrow(
            "month 0 is out of range",
        );
        expect(() => evaluateExpr("relativedelta(hour=25)")).toThrow(
            "hour 25 is out of range",
        );
        expect(() => evaluateExpr("relativedelta(minute=61)")).toThrow(
            "minute 61 is out of range",
        );
        expect(() => evaluateExpr("relativedelta(second=61)")).toThrow(
            "second 61 is out of range",
        );
        expect(() => evaluateExpr("relativedelta(day=0)")).toThrow(
            "day 0 is out of range",
        );
        expect(() => evaluateExpr("relativedelta(year=0)")).toThrow(
            "year 0 is out of range",
        );
        // day past month-end is VALID: dateutil clamps to the last day
        expect(
            evaluateExpr(
                "(datetime.date(2020,2,10) + relativedelta(day=45)).strftime('%Y-%m-%d')",
            ),
        ).toBe("2020-02-29");
        // boundary values pass
        expect(() => evaluateExpr("relativedelta(month=12, hour=23)")).not.toThrow();
        // relative (plural) args stay unbounded
        expect(() => evaluateExpr("relativedelta(months=-15)")).not.toThrow();
    });

    test("adding date and relative delta", () => {
        const expr1 =
            "(datetime.date(day=3,month=4,year=2001) + relativedelta(day=1)).strftime('%Y-%m-%d')";
        expect(evaluateExpr(expr1)).toBe("2001-04-01");

        const expr2 =
            "(datetime.date(day=3,month=4,year=2001) + relativedelta(month=1)).strftime('%Y-%m-%d')";
        expect(evaluateExpr(expr2)).toBe("2001-01-03");

        const expr3 =
            "(datetime.date(2021,10,1) + relativedelta(hours=12)).strftime('%Y-%m-%d %H:%M:%S')";
        expect(evaluateExpr(expr3)).toBe("2021-10-01 12:00:00");

        const expr4 =
            "(datetime.date(2021,10,1) + relativedelta(day=15,days=3)).strftime('%Y-%m-%d')";
        expect(evaluateExpr(expr4)).toBe("2021-10-18");

        const expr5 =
            "(datetime.date(2021,10,1) - relativedelta(day=15,days=3)).strftime('%Y-%m-%d')";
        expect(evaluateExpr(expr5)).toBe("2021-10-12");

        const expr6 =
            "(datetime.date(2021,10,1) + relativedelta(day=15,days=3,hours=24)).strftime('%Y-%m-%d')";
        expect(evaluateExpr(expr6)).toBe("2021-10-19");
    });

    test("adding relative delta and date", () => {
        const expr =
            "(relativedelta(day=1) + datetime.date(day=3,month=4,year=2001)).strftime('%Y-%m-%d')";
        expect(evaluateExpr(expr)).toBe("2001-04-01");
    });

    test("subtracting date and relative delta", () => {
        const expr1 =
            "(datetime.date(day=3,month=4,year=2001) - relativedelta(day=1)).strftime('%Y-%m-%d')";
        expect(evaluateExpr(expr1)).toBe("2001-04-01");

        const expr3 =
            "(datetime.date(day=3,month=4,year=2001) - relativedelta(day=1)).strftime('%Y-%m-%d')";
        expect(evaluateExpr(expr3)).toBe("2001-04-01");
    });

    test("type of date + relative delta", () => {
        const expr1 =
            "(datetime.date(2021,10,1) + relativedelta(day=15,days=3,hours=24))";
        expect(evaluateExpr(expr1)).toBeInstanceOf(PyDate);
    });
});

describe("relative delta weekday", () => {
    test("add or subtract weekday", () => {
        const expr1 =
            "(datetime.date(day=3,month=4,year=2001) - relativedelta(day=1, weekday=3)).strftime('%Y-%m-%d')";
        expect(evaluateExpr(expr1)).toBe("2001-04-05");

        const expr2 =
            "(datetime.date(day=29,month=4,year=2001) - relativedelta(weekday=4)).strftime('%Y-%m-%d')";
        expect(evaluateExpr(expr2)).toBe("2001-05-04");

        const expr3 =
            "(datetime.date(day=6,month=4,year=2001) - relativedelta(weekday=0)).strftime('%Y-%m-%d')";
        expect(evaluateExpr(expr3)).toBe("2001-04-09");

        const expr4 =
            "(datetime.date(day=1,month=4,year=2001) + relativedelta(weekday=-2)).strftime('%Y-%m-%d')";
        expect(evaluateExpr(expr4)).toBe("2001-04-07");

        const expr5 =
            "(datetime.date(day=11,month=4,year=2001) + relativedelta(weekday=2)).strftime('%Y-%m-%d')";
        expect(evaluateExpr(expr5)).toBe("2001-04-11");

        const expr6 =
            "(datetime.date(day=11,month=4,year=2001) + relativedelta(weekday=-2)).strftime('%Y-%m-%d')";
        expect(evaluateExpr(expr6)).toBe("2001-04-14");

        const expr7 =
            "(datetime.date(day=11,month=4,year=2001) + relativedelta(weekday=0)).strftime('%Y-%m-%d')";
        expect(evaluateExpr(expr7)).toBe("2001-04-16");

        const expr8 =
            "(datetime.date(day=11,month=4,year=2001) + relativedelta(weekday=1)).strftime('%Y-%m-%d')";
        expect(evaluateExpr(expr8)).toBe("2001-04-17");
    });
});

describe("relative delta yearday nlyearday", () => {
    test("yearday", () => {
        const expr1 =
            "(datetime.date(day=3,month=4,year=2001) - relativedelta(year=2000, yearday=60)).strftime('%Y-%m-%d')";
        expect(evaluateExpr(expr1)).toBe("2000-02-29");

        const expr2 =
            "(datetime.date(day=3,month=4,year=2001) - relativedelta(yearday=60)).strftime('%Y-%m-%d')";
        expect(evaluateExpr(expr2)).toBe("2001-03-01");

        const expr3 =
            "(datetime.date(1999,12,31) + relativedelta(days=1, yearday=60)).strftime('%Y-%m-%d')";
        expect(evaluateExpr(expr3)).toBe("1999-03-02");
    });

    test("nlyearday", () => {
        const expr1 =
            "(datetime.date(day=3,month=4,year=2001) + relativedelta(year=2000, nlyearday=60)).strftime('%Y-%m-%d')";
        expect(evaluateExpr(expr1)).toBe("2000-03-01");

        const expr2 =
            "(datetime.date(day=3,month=4,year=2001) + relativedelta(nlyearday=60)).strftime('%Y-%m-%d')";
        expect(evaluateExpr(expr2)).toBe("2001-03-01");
    });
});

describe("ordering comparisons", () => {
    test("date relational comparisons", () => {
        expect(evaluateExpr("datetime.date(2020,1,1) < datetime.date(2021,1,1)")).toBe(
            true,
        );
        expect(evaluateExpr("datetime.date(2020,1,1) > datetime.date(2021,1,1)")).toBe(
            false,
        );
        expect(evaluateExpr("datetime.date(2020,1,1) <= datetime.date(2021,1,1)")).toBe(
            true,
        );
        expect(evaluateExpr("datetime.date(2020,1,1) >= datetime.date(2021,1,1)")).toBe(
            false,
        );
        expect(evaluateExpr("datetime.date(2021,1,1) <= datetime.date(2021,1,1)")).toBe(
            true,
        );
        expect(evaluateExpr("datetime.date(2021,1,1) >= datetime.date(2021,1,1)")).toBe(
            true,
        );
        expect(evaluateExpr("datetime.date(2021,1,1) < datetime.date(2021,1,1)")).toBe(
            false,
        );

        const ctx = {
            d1: PyDate.create(2020, 6, 15),
            d2: PyDate.create(2020, 6, 16),
        };
        expect(evaluateExpr("d1 < d2", ctx)).toBe(true);
        expect(evaluateExpr("d2 > d1", ctx)).toBe(true);
    });

    test("datetime relational comparisons", () => {
        expect(
            evaluateExpr(
                "datetime.datetime(2021,1,1,0,0,1) > datetime.datetime(2021,1,1,0,0,0)",
            ),
        ).toBe(true);
        expect(
            evaluateExpr(
                "datetime.datetime(2021,1,1,0,0,0,1) > datetime.datetime(2021,1,1)",
            ),
        ).toBe(true);
        expect(
            evaluateExpr(
                "datetime.datetime(2021,1,1) < datetime.datetime(2020,12,31,23,59,59)",
            ),
        ).toBe(false);
    });

    test("max/min over dates", () => {
        expect(
            evaluateExpr(
                "max(datetime.date(2020,1,1), datetime.date(2021,1,1)).strftime('%Y-%m-%d')",
            ),
        ).toBe("2021-01-01");
        expect(
            evaluateExpr(
                "max(datetime.date(2021,1,1), datetime.date(2020,1,1)).strftime('%Y-%m-%d')",
            ),
        ).toBe("2021-01-01");
        expect(
            evaluateExpr(
                "min(datetime.date(2020,1,1), datetime.date(2021,1,1)).strftime('%Y-%m-%d')",
            ),
        ).toBe("2020-01-01");
        expect(
            evaluateExpr(
                "min(datetime.date(2021,1,1), datetime.date(2020,1,1)).strftime('%Y-%m-%d')",
            ),
        ).toBe("2020-01-01");
    });

    test("timedelta ordering", () => {
        expect(
            evaluateExpr("datetime.timedelta(days=1) < datetime.timedelta(days=2)"),
        ).toBe(true);
        expect(
            evaluateExpr("datetime.timedelta(days=2) < datetime.timedelta(days=1)"),
        ).toBe(false);
        expect(
            evaluateExpr("datetime.timedelta(hours=-1) < datetime.timedelta(0)"),
        ).toBe(true);
        expect(
            evaluateExpr("datetime.timedelta(days=1) <= datetime.timedelta(hours=24)"),
        ).toBe(true);
        expect(
            evaluateExpr(
                "max(datetime.timedelta(days=1), datetime.timedelta(days=2)).days",
            ),
        ).toBe(2);
    });
});

describe("misc", () => {
    test("context_today", () => {
        expect(check("context_today().strftime('%Y-%m-%d')", formatDate)).toBe(true);
    });

    test("today", () => {
        expect(check("today", formatDate)).toBe(true);
    });

    test("now", () => {
        expect(check("now", formatDateTimeUTC)).toBe(true);
    });

    test("current_date", () => {
        mockDate("2021-09-20 10:00:00");
        expect(evaluateExpr("current_date")).toBe("2021-09-20");
    });
});

describe("relativedelta leapdays", () => {
    test("leapdays kwarg is applied (leap year, past February)", () => {
        // dateutil: leapdays are added when the result's year is a leap year
        // and the result is past Feb 28.
        expect(
            evaluateExpr(
                "(datetime.date(2020,1,1) + relativedelta(months=2, leapdays=10)).strftime('%Y-%m-%d')",
            ),
        ).toBe("2020-03-11");
        // Non-leap year: leapdays are ignored.
        expect(
            evaluateExpr(
                "(datetime.date(2021,1,1) + relativedelta(months=2, leapdays=10)).strftime('%Y-%m-%d')",
            ),
        ).toBe("2021-03-01");
    });

    test("negation keeps leapdays unsigned (dateutil parity)", () => {
        // dateutil's __neg__ does NOT negate leapdays: subtracting the delta
        // still ADDS the (positive) leapdays when the result is past Feb 28
        // of a leap year.
        expect(
            evaluateExpr(
                "(datetime.date(2020,6,1) - relativedelta(months=1, leapdays=1)).strftime('%Y-%m-%d')",
            ),
        ).toBe("2020-05-02");
    });
});

describe("construction validation", () => {
    test("date() rejects out-of-range and missing components", () => {
        expect(() => evaluateExpr("datetime.date(2020, 13, 45)")).toThrow(
            /month must be in 1\.\.12/,
        );
        expect(() => evaluateExpr("datetime.date(2020, 2, 30)")).toThrow(
            /day is out of range/,
        );
        expect(() => evaluateExpr("datetime.date(2020, 1)")).toThrow(
            /day must be an integer/,
        );
        // valid dates still work
        expect(evaluateExpr("datetime.date(2020, 2, 29).strftime('%Y-%m-%d')")).toBe(
            "2020-02-29",
        );
    });

    test("datetime()/time() range-validate the time components", () => {
        expect(() => evaluateExpr("datetime.datetime(2020, 1, 1, 25, 0, 0)")).toThrow(
            /hour must be in 0\.\.23/,
        );
        expect(() => evaluateExpr("datetime.time(10, 61)")).toThrow(
            /minute must be in 0\.\.59/,
        );
    });

    test("datetime()/time() reject non-integer time components", () => {
        // CPython raises TypeError on a float hour; without an integer check
        // the value flowed into strftime yielding garbage like "5.5:00:00".
        expect(() => evaluateExpr("datetime.datetime(2020, 1, 1, 5.5)")).toThrow(
            /hour must be an integer/,
        );
        expect(() => evaluateExpr("datetime.time(1, 2.5)")).toThrow(
            /minute must be an integer/,
        );
    });
});
