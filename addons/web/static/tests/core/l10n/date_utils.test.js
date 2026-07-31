// @ts-check

import { describe, expect, test } from "@odoo/hoot";
import { getLocalYearAndWeek, isInRange } from "@web/core/l10n/date_utils";
import { localization } from "@web/core/l10n/localization";
import { luxon } from "@web/core/l10n/luxon";

const { DateTime } = luxon;

describe.current.tags("headless");

/**
 * Run `fn` with `localization.weekStart` set, restoring it afterwards.
 *
 * `localization` is a Proxy whose `get` trap THROWS for any key the
 * localization service has not populated yet, so the previous value must be
 * probed with `Object.hasOwn` before it can be read — the trap fires on a plain
 * read, and only `get` is trapped, which is why `hasOwn`/`delete` are safe.
 *
 * Deliberately not `patchWithCleanup`: this file needs exactly one scalar
 * swapped, and that helper drags in `web_test_helpers`' whole mock-server import
 * graph. Restoring in `finally` also keeps each loop iteration below
 * independent, which an end-of-test cleanup would not.
 *
 * @param {number} weekStart
 * @param {() => void} fn
 */
function withWeekStart(weekStart, fn) {
    const had = Object.hasOwn(localization, "weekStart");
    const previous = had ? localization.weekStart : undefined;
    localization.weekStart = weekStart;
    try {
        fn();
    } finally {
        if (had) {
            localization.weekStart = previous;
        } else {
            delete (/** @type {any} */ (localization).weekStart);
        }
    }
}

// `getLocalYearAndWeek` renders the calendar views' week column and web_gantt's
// week label, and had no test at all -- including none for the one property that
// makes its `weekStart > 1 && weekStart < 5` branch checkable.
describe("getLocalYearAndWeek", () => {
    test("weekStart=1 reproduces ISO-8601 numbering, 2015-2030", () => {
        let checked = 0;
        const mismatches = [];
        withWeekStart(1, () => {
            for (let year = 2015; year <= 2030; year++) {
                // Only the days where ISO numbering is interesting: the year
                // boundaries (where the week-year diverges from the calendar year)
                // and one mid-year sample per month.
                const days = [
                    ...[0, 1, 2, 3, 4, 5, 6].map((d) =>
                        DateTime.local(year, 1, 1).plus({ days: d }),
                    ),
                    ...[6, 5, 4, 3, 2, 1, 0].map((d) =>
                        DateTime.local(year, 12, 31).minus({ days: d }),
                    ),
                    ...Array.from({ length: 12 }, (_, m) =>
                        DateTime.local(year, m + 1, 15),
                    ),
                ];
                for (const date of days) {
                    checked++;
                    const { year: gotYear, week } = getLocalYearAndWeek(date);
                    if (week !== date.weekNumber || gotYear !== date.weekYear) {
                        mismatches.push(
                            `${date.toISODate()}: got w${week}/${gotYear}, ISO w${date.weekNumber}/${date.weekYear}`,
                        );
                    }
                }
            }
        });
        expect(mismatches).toEqual([]);
        expect(checked).toBe(416);
    });

    test("startDate is always the first day of the LOCAL week", () => {
        for (const weekStart of [1, 2, 3, 4, 5, 6, 7]) {
            withWeekStart(weekStart, () => {
                for (let offset = 0; offset < 7; offset++) {
                    const date = DateTime.local(2026, 7, 27).plus({ days: offset });
                    const { startDate } = getLocalYearAndWeek(date);
                    expect(startDate.weekday).toBe(weekStart, {
                        message: `weekStart=${weekStart}, date=${date.toISODate()}`,
                    });
                    // The week start is at or before the date, within 6 days of it.
                    const back = date.diff(startDate, "days").days;
                    expect(back >= 0 && back < 7).toBe(true, {
                        message: `weekStart=${weekStart}, date=${date.toISODate()}, startDate=${startDate.toISODate()}`,
                    });
                }
            });
        }
    });

    test("the number follows the ISO week the local week most overlaps", () => {
        // 2026-07-29 is a Wednesday. Every weekStart puts it in ISO week 31
        // except Thursday, whose local week (Jul 23-29) shares only 4 days with
        // week 31 and is therefore numbered 30 -- the tie broken toward the
        // earlier week. This is the single assertion that pins the
        // `weekStart > 1 && weekStart < 5` branch.
        const byWeekStart = {};
        for (const weekStart of [1, 2, 3, 4, 5, 6, 7]) {
            withWeekStart(weekStart, () => {
                byWeekStart[weekStart] = getLocalYearAndWeek(
                    DateTime.local(2026, 7, 29),
                ).week;
            });
        }
        expect(byWeekStart).toEqual({
            1: 31,
            2: 31,
            3: 31,
            4: 30,
            5: 31,
            6: 31,
            7: 31,
        });
    });

    test("year rolls over with the week, not with the calendar", () => {
        // 2025-12-29 is a Monday: ISO week 1 of 2026 already. A Tuesday-start
        // locale still has it in the previous week, a Friday-start one does not.
        const seen = {};
        for (const weekStart of [1, 2, 5, 7]) {
            withWeekStart(weekStart, () => {
                const { year, week } = getLocalYearAndWeek(
                    DateTime.local(2025, 12, 29),
                );
                seen[weekStart] = `${week}/${year}`;
            });
        }
        expect(seen).toEqual({ 1: "1/2026", 2: "52/2025", 5: "1/2026", 7: "1/2026" });
    });

    test("accepts a plain JS Date as well as a Luxon DateTime", () => {
        withWeekStart(1, () => {
            const luxonDate = DateTime.local(2026, 7, 29);
            const fromJs = getLocalYearAndWeek(luxonDate.toJSDate());
            const fromLuxon = getLocalYearAndWeek(luxonDate);
            expect(fromJs.week).toBe(fromLuxon.week);
            expect(fromJs.year).toBe(fromLuxon.year);
            expect(fromJs.startDate.toISODate()).toBe(fromLuxon.startDate.toISODate());
        });
    });
});

describe("isInRange", () => {
    test("single DateTime value", () => {
        const range = [
            DateTime.fromISO("2024-01-01T10:20:00Z"),
            DateTime.fromISO("2024-01-01T10:40:00Z"),
        ];
        expect(isInRange(DateTime.fromISO("2024-01-01T10:30:00Z"), range)).toBe(true);
        expect(isInRange(DateTime.fromISO("2024-01-01T12:00:00Z"), range)).toBe(false);
    });

    test("falsy value or range", () => {
        const range = [
            DateTime.fromISO("2024-01-01T10:20:00Z"),
            DateTime.fromISO("2024-01-01T10:40:00Z"),
        ];
        expect(isInRange(null, range)).toBe(false);
        expect(isInRange(DateTime.now(), null)).toBe(false);
    });

    test("array with a single truthy value falls back to single-value check", () => {
        const range = [
            DateTime.fromISO("2024-01-01T10:20:00Z"),
            DateTime.fromISO("2024-01-01T10:40:00Z"),
        ];
        expect(isInRange([DateTime.fromISO("2024-01-01T10:30:00Z"), null], range)).toBe(
            true,
        );
        expect(isInRange([null, DateTime.fromISO("2024-01-01T12:00:00Z")], range)).toBe(
            false,
        );
    });

    test("sorts a mixed-offset array chronologically, not by ISO string", () => {
        const earlier = DateTime.fromISO("2024-01-01T10:00:00", { zone: "UTC" });
        const later = DateTime.fromISO("2024-01-01T11:00:00", { zone: "UTC" }).setZone(
            "UTC-10",
        );
        const insideRange = [
            DateTime.fromISO("2024-01-01T10:20:00Z"),
            DateTime.fromISO("2024-01-01T10:40:00Z"),
        ];
        const outsideRange = [
            DateTime.fromISO("2024-01-01T12:00:00Z"),
            DateTime.fromISO("2024-01-01T13:00:00Z"),
        ];
        expect(isInRange([later, earlier], insideRange)).toBe(true);
        expect(isInRange([earlier, later], insideRange)).toBe(true);
        expect(isInRange([later, earlier], outsideRange)).toBe(false);
    });
});
