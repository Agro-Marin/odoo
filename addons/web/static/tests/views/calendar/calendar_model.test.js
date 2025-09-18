// @ts-check

/**
 * Pure unit tests for calendar model logic.
 *
 * Tests the core computation functions extracted from calendar_model.js into
 * pure utility modules. No OWL environment, ORM calls, or DOM fixtures needed.
 * (CalendarModel.setup() calls useDebounced, an OWL hook, so the model class
 * itself requires an OWL component context to instantiate.)
 *
 * Modules under test:
 *  - views/calendar/calendar_date_range.js — range computation and domain building
 *  - views/calendar/calendar_record.js     — raw record normalization
 */

import { describe, expect, test } from "@odoo/hoot";
import {
    computeCalendarRange,
    computeFiltersDomain,
    computeRangeDomain,
} from "@web/views/calendar/calendar_date_range";
import { normalizeCalendarRecord } from "@web/views/calendar/calendar_record";

// luxon is available as a module-level global in the Hoot browser environment
const { DateTime } = luxon;

// ---------------------------------------------------------------------------
// computeCalendarRange — scale-based date range computation
// ---------------------------------------------------------------------------

describe("computeCalendarRange — day scale", () => {
    test("returns the full day containing the anchor date", () => {
        // Jan 15, 2024 — a Monday
        const date = DateTime.fromISO("2024-01-15T14:30:00");

        const { start, end } = computeCalendarRange("day", date, 1, false);

        expect(start.day).toBe(15);
        expect(start.hour).toBe(0);
        expect(start.minute).toBe(0);
        expect(end.day).toBe(15);
        expect(end.hour).toBe(23);
        expect(end.minute).toBe(59);
    });
});

describe("computeCalendarRange — week scale, Monday start", () => {
    test("returns Mon–Sun when firstDayOfWeek=1 and anchor is a Wednesday", () => {
        // Jan 17, 2024 is a Wednesday (ISO weekday 3)
        const date = DateTime.fromISO("2024-01-17");

        const { start, end } = computeCalendarRange("week", date, 1, false);

        // Monday Jan 15 → Sunday Jan 21
        expect(start.day).toBe(15);
        expect(start.month).toBe(1);
        expect(end.day).toBe(21);
        expect(end.month).toBe(1);
    });

    test("anchor on Monday itself is already the start of the week", () => {
        const date = DateTime.fromISO("2024-01-15"); // Monday

        const { start } = computeCalendarRange("week", date, 1, false);

        expect(start.day).toBe(15);
    });

    test("anchor on Sunday returns preceding Monday as start", () => {
        // Jan 21, 2024 is a Sunday (ISO weekday 7)
        const date = DateTime.fromISO("2024-01-21");

        const { start, end } = computeCalendarRange("week", date, 1, false);

        // Start should be Mon Jan 15; end should be Sun Jan 21
        expect(start.day).toBe(15);
        expect(end.day).toBe(21);
    });
});

describe("computeCalendarRange — week scale, Sunday start", () => {
    test("returns Sun–Sat when firstDayOfWeek=0 and anchor is a Wednesday", () => {
        // Jan 17, 2024 (Wednesday, ISO weekday 3)
        const date = DateTime.fromISO("2024-01-17");

        const { start, end } = computeCalendarRange("week", date, 0, false);

        // Sunday Jan 14 → Saturday Jan 20
        expect(start.day).toBe(14);
        expect(end.day).toBe(20);
    });
});

describe("computeCalendarRange — month scale, no overflow", () => {
    test("returns startOf month to endOf month", () => {
        const date = DateTime.fromISO("2024-01-17");

        const { start, end } = computeCalendarRange("month", date, 1, false);

        expect(start.day).toBe(1);
        expect(start.month).toBe(1);
        expect(end.day).toBe(31);
        expect(end.month).toBe(1);
    });
});

describe("computeCalendarRange — month scale, with overflow", () => {
    test("returns a 6-week range starting from the aligned first day of the first week", () => {
        // January 2024: starts on Monday (Jan 1 = Mon, firstDayOfWeek=1)
        // → start = Jan 1, end = Jan 1 + 6 weeks - 1 day = Feb 11
        const date = DateTime.fromISO("2024-01-17");

        const { start, end } = computeCalendarRange("month", date, 1, true);

        expect(start.day).toBe(1);
        expect(start.month).toBe(1);
        // 6 weeks from Jan 1 - 1 day = Feb 11
        expect(end.month).toBe(2);
        expect(end.day).toBe(11);
    });

    test("start aligns to firstDayOfWeek when month begins mid-week", () => {
        // February 2024 starts on Thursday (ISO weekday 4); firstDayOfWeek=1 (Monday)
        // currentWeekOffset = (4 - 1) % 7 = 3 → start = Feb 1 - 3 = Jan 29
        const date = DateTime.fromISO("2024-02-15");

        const { start } = computeCalendarRange("month", date, 1, true);

        expect(start.month).toBe(1);
        expect(start.day).toBe(29);
    });
});

// ---------------------------------------------------------------------------
// computeRangeDomain — overlap domain construction
// ---------------------------------------------------------------------------

describe("computeRangeDomain — with date_stop", () => {
    test("produces two-condition domain for events overlapping the range", () => {
        const range = {
            start: DateTime.fromISO("2024-01-15"),
            end: DateTime.fromISO("2024-01-21"),
        };

        const domain = computeRangeDomain(
            { date_start: "start_date", date_stop: "stop_date" },
            "date",
            range,
        );

        // date_start <= end AND date_stop >= start
        expect(domain.length).toBe(2);
        expect(domain[0][0]).toBe("start_date");
        expect(domain[0][1]).toBe("<=");
        expect(domain[1][0]).toBe("stop_date");
        expect(domain[1][1]).toBe(">=");
    });
});

describe("computeRangeDomain — without date_stop, without date_delay", () => {
    test("produces two-condition domain restricting date_start to the range", () => {
        const range = {
            start: DateTime.fromISO("2024-01-15"),
            end: DateTime.fromISO("2024-01-21"),
        };

        const domain = computeRangeDomain(
            { date_start: "start_date" }, // no date_stop, no date_delay
            "date",
            range,
        );

        // date_start <= end AND date_start >= start
        expect(domain.length).toBe(2);
        expect(domain[0][0]).toBe("start_date");
        expect(domain[0][1]).toBe("<=");
        expect(domain[1][0]).toBe("start_date");
        expect(domain[1][1]).toBe(">=");
    });
});

describe("computeRangeDomain — with date_delay (no date_stop)", () => {
    test("produces only an upper-bound condition when date_delay is present", () => {
        const range = {
            start: DateTime.fromISO("2024-01-15"),
            end: DateTime.fromISO("2024-01-21"),
        };

        const domain = computeRangeDomain(
            { date_start: "start_date", date_delay: "planned_hours" },
            "datetime",
            range,
        );

        // Only the upper bound: date_start <= end
        expect(domain.length).toBe(1);
        expect(domain[0][0]).toBe("start_date");
        expect(domain[0][1]).toBe("<=");
    });
});

describe("computeRangeDomain — serialization format", () => {
    test("date type serializes to YYYY-MM-DD strings", () => {
        const range = {
            start: DateTime.fromISO("2024-01-15"),
            end: DateTime.fromISO("2024-01-21"),
        };

        const domain = computeRangeDomain(
            { date_start: "start_date" },
            "date",
            range,
        );

        // Values should be ISO date strings
        expect(typeof domain[0][2]).toBe("string");
        expect(domain[0][2]).toMatch(/^\d{4}-\d{2}-\d{2}/);
    });
});

// ---------------------------------------------------------------------------
// computeFiltersDomain — filter section → domain conversion
// ---------------------------------------------------------------------------

describe("computeFiltersDomain — static filters (writeResModel)", () => {
    test("produces 'in' domain from active static filter values", () => {
        const filterSections = {
            user_id: {
                filters: [
                    { value: 1, active: true },
                    { value: 2, active: false },
                    { value: 3, active: true },
                ],
            },
        };
        const filtersInfo = {
            user_id: { writeResModel: "res.users" },
        };

        const domain = computeFiltersDomain(filterSections, filtersInfo);

        expect(domain.length).toBe(1);
        expect(domain[0][0]).toBe("user_id");
        expect(domain[0][1]).toBe("in");
        expect(domain[0][2]).toEqual([1, 3]);
    });

    test("produces 'in []' domain when no static filters are active (excludes all records)", () => {
        const filterSections = {
            user_id: { filters: [{ value: 1, active: false }] },
        };
        const filtersInfo = { user_id: { writeResModel: "res.users" } };

        const domain = computeFiltersDomain(filterSections, filtersInfo);

        expect(domain.length).toBe(1);
        expect(domain[0]).toEqual(["user_id", "in", []]);
    });
});

describe("computeFiltersDomain — dynamic filters (no writeResModel)", () => {
    test("produces 'not in' domain from inactive dynamic filter values", () => {
        const filterSections = {
            categ_id: {
                filters: [
                    { value: 10, active: true },
                    { value: 20, active: false }, // excluded
                    { value: 30, active: false }, // excluded
                ],
            },
        };
        const filtersInfo = {
            categ_id: {}, // no writeResModel → dynamic
        };

        const domain = computeFiltersDomain(filterSections, filtersInfo);

        expect(domain.length).toBe(1);
        expect(domain[0][0]).toBe("categ_id");
        expect(domain[0][1]).toBe("not in");
        expect(domain[0][2]).toEqual([20, 30]);
    });

    test("produces no domain when all dynamic values are active", () => {
        const filterSections = {
            categ_id: { filters: [{ value: 1, active: true }] },
        };
        const filtersInfo = { categ_id: {} };

        const domain = computeFiltersDomain(filterSections, filtersInfo);

        expect(domain.length).toBe(0);
    });
});

describe("computeFiltersDomain — mixed static and dynamic", () => {
    test("produces separate clauses for each field", () => {
        const filterSections = {
            user_id: { filters: [{ value: 1, active: true }] },
            categ_id: { filters: [{ value: 10, active: false }] },
        };
        const filtersInfo = {
            user_id: { writeResModel: "res.users" },
            categ_id: {},
        };

        const domain = computeFiltersDomain(filterSections, filtersInfo);

        const fields = domain.map((d) => d[0]);
        expect(fields).toInclude("user_id");
        expect(fields).toInclude("categ_id");

        const userClause = domain.find((d) => d[0] === "user_id");
        const categClause = domain.find((d) => d[0] === "categ_id");
        expect(userClause[1]).toBe("in");
        expect(categClause[1]).toBe("not in");
    });
});

// ---------------------------------------------------------------------------
// normalizeCalendarRecord — raw record transformation
// ---------------------------------------------------------------------------

describe("normalizeCalendarRecord — datetime event (timed)", () => {
    test("extracts id, title, start/end DateTimes, and isAllDay=false", () => {
        const rawRecord = {
            id: 42,
            display_name: "Team Meeting",
            start_datetime: "2024-01-15 10:00:00",
            stop_datetime: "2024-01-15 11:00:00",
        };
        const fields = {
            start_datetime: { type: "datetime" },
            stop_datetime: { type: "datetime" },
        };
        const fieldMapping = {
            date_start: "start_datetime",
            date_stop: "stop_datetime",
        };

        const result = normalizeCalendarRecord(rawRecord, {
            fields,
            fieldMapping,
            isTimeHidden: false,
            scale: "week",
            isSmall: false,
        });

        expect(result.id).toBe(42);
        expect(result.title).toBe("Team Meeting");
        expect(result.isAllDay).toBe(false);
        expect(result.start.day).toBe(15);
        expect(result.end.day).toBe(15);
        expect(result.isMonth).toBe(false);
        expect(result.isSmall).toBe(false);
    });
});

describe("normalizeCalendarRecord — date event (all-day)", () => {
    test("sets isAllDay=true and isTimeHidden=true for date-type fields", () => {
        const rawRecord = {
            id: 1,
            display_name: "Holiday",
            start_date: "2024-01-15",
            stop_date: "2024-01-16",
        };
        const fields = {
            start_date: { type: "date" },
            stop_date: { type: "date" },
        };

        const result = normalizeCalendarRecord(rawRecord, {
            fields,
            fieldMapping: { date_start: "start_date", date_stop: "stop_date" },
            isTimeHidden: false,
            scale: "month",
            isSmall: false,
        });

        expect(result.isAllDay).toBe(true);
        // date fields never show time
        expect(result.isTimeHidden).toBe(true);
        expect(result.isMonth).toBe(true);
    });
});

describe("normalizeCalendarRecord — all_day flag override", () => {
    test("sets isAllDay=true when all_day field is truthy on the record", () => {
        const rawRecord = {
            id: 1,
            display_name: "All Day Event",
            start_dt: "2024-01-15 00:00:00",
            is_all_day: true,
        };
        const fields = {
            start_dt: { type: "datetime" },
        };

        const result = normalizeCalendarRecord(rawRecord, {
            fields,
            fieldMapping: { date_start: "start_dt", all_day: "is_all_day" },
            isTimeHidden: false,
            scale: "day",
            isSmall: false,
        });

        expect(result.isAllDay).toBe(true);
    });
});

describe("normalizeCalendarRecord — color extraction", () => {
    test("uses numeric color value directly as colorIndex", () => {
        const rawRecord = {
            id: 1,
            display_name: "X",
            start_dt: "2024-01-15 10:00:00",
            color_value: 7,
        };
        const fields = { start_dt: { type: "datetime" } };

        const result = normalizeCalendarRecord(rawRecord, {
            fields,
            fieldMapping: { date_start: "start_dt", color: "color_value" },
            isTimeHidden: false,
            scale: "week",
            isSmall: false,
        });

        expect(result.colorIndex).toBe(7);
    });

    test("extracts id from many2one color value", () => {
        const rawRecord = {
            id: 1,
            display_name: "X",
            start_dt: "2024-01-15 10:00:00",
            color_field: [3, "Red Team"],
        };
        const fields = { start_dt: { type: "datetime" } };

        const result = normalizeCalendarRecord(rawRecord, {
            fields,
            fieldMapping: { date_start: "start_dt", color: "color_field" },
            isTimeHidden: false,
            scale: "week",
            isSmall: false,
        });

        expect(result.colorIndex).toBe(3);
    });
});

describe("normalizeCalendarRecord — duration fallback", () => {
    test("uses duration=1 when date_delay field is absent", () => {
        const rawRecord = {
            id: 1,
            display_name: "X",
            start_dt: "2024-01-15 10:00:00",
        };
        const fields = { start_dt: { type: "datetime" } };

        const result = normalizeCalendarRecord(rawRecord, {
            fields,
            fieldMapping: { date_start: "start_dt" },
            isTimeHidden: false,
            scale: "week",
            isSmall: false,
        });

        expect(result.duration).toBe(1);
    });

    test("applies duration to compute end when no date_stop given", () => {
        const rawRecord = {
            id: 1,
            display_name: "X",
            start_dt: "2024-01-15 10:00:00",
            planned_hours: 3,
        };
        const fields = { start_dt: { type: "datetime" } };

        const result = normalizeCalendarRecord(rawRecord, {
            fields,
            fieldMapping: { date_start: "start_dt", date_delay: "planned_hours" },
            isTimeHidden: false,
            scale: "week",
            isSmall: false,
        });

        // end = start + 3 hours — check relative diff, not absolute hour (timezone-agnostic)
        expect(result.end.diff(result.start, "hours").hours).toBe(3);
    });
});
