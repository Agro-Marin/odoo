// @ts-check

import { describe, expect, test } from "@odoo/hoot";
import { DateTime } from "@web/core/l10n/luxon";
import {
    baseEventClassNames,
    convertRecordToEvent,
    getColor,
    getFormattedDateSpan,
    sortCalendarFilters,
} from "@web/views/calendar/calendar_utils";

describe.current.tags("headless");

const dt = (/** @type {string} */ iso) => DateTime.fromISO(iso);

test("getColor: css colours pass through, numbers cycle over 55, strings hash to 24", () => {
    expect(getColor(false)).toBe(false);
    expect(getColor("#ABC")).toBe("#ABC");
    expect(getColor("rgba(1, 2, 3, 0.5)")).toBe("rgba(1, 2, 3, 0.5)");
    expect(getColor("rgba(1,2,3,0.5)")).toBe("rgba(1,2,3,0.5)");
    expect(getColor("hsl(120, 50%, 50%)")).toBe("hsl(120, 50%, 50%)");
    expect(getColor(1)).toBe(1);
    expect(getColor(55)).toBe(55);
    expect(getColor(56)).toBe(1);
    const fromString = /** @type {number} */ (getColor("some key"));
    expect(fromString).toBeGreaterThan(0);
    expect(fromString).toBeLessThan(25);
    expect(getColor("some key")).toBe(fromString);
});

test("convertRecordToEvent: an all-day or day-spanning event ends the day after", () => {
    const record = {
        id: 7,
        title: "T",
        start: dt("2024-03-10T09:00:00"),
        end: dt("2024-03-10T10:00:00"),
        isAllDay: false,
    };
    expect(convertRecordToEvent(record)).toEqual({
        id: 7,
        title: "T",
        start: record.start.toISO(),
        end: record.end.toISO(),
        allDay: false,
    });
    const allDay = {
        ...record,
        isAllDay: true,
        start: dt("2024-03-10"),
        end: dt("2024-03-11"),
    };
    expect(convertRecordToEvent(allDay).end).toBe(dt("2024-03-12").toISO());
    expect(convertRecordToEvent(allDay).allDay).toBe(true);
    const forced = convertRecordToEvent(record, true);
    expect(forced.allDay).toBe(true);
    expect(forced.end).toBe(dt("2024-03-11T10:00:00").toISO());
});

test("sortCalendarFilters: by type priority, then active dynamic first, then label", () => {
    const filters = [
        { type: "dynamic", value: false, label: "zed" },
        { type: "record", value: 1, label: "beta" },
        { type: "dynamic", value: 3, label: "alpha" },
        { type: "user", value: 2, label: "me" },
        { type: "record", value: 4, label: "Alpha" },
    ];
    const sorted = sortCalendarFilters(filters, ["user", "record", "dynamic"]);
    expect(sorted.map((f) => `${f.type}:${f.label}`)).toEqual([
        "user:me",
        "record:Alpha",
        "record:beta",
        "dynamic:alpha",
        "dynamic:zed",
    ]);
    expect(filters[0].label).toBe("zed");
});

test("getFormattedDateSpan: same day, same month, different months", () => {
    expect(getFormattedDateSpan(dt("2024-03-10"), dt("2024-03-10"))).toBe(
        dt("2024-03-10").toFormat("DDD"),
    );
    expect(getFormattedDateSpan(dt("2024-03-10"), dt("2024-03-12"))).toBe(
        "March 10-12, 2024",
    );
    expect(getFormattedDateSpan(dt("2024-03-30"), dt("2024-04-02"))).toBe(
        `${dt("2024-03-30").toFormat("DDD")} - ${dt("2024-04-02").toFormat("DDD")}`,
    );
});

test("baseEventClassNames: colour index, css colour, hatched and striked", () => {
    expect(baseEventClassNames(null)).toEqual(["o_event"]);
    expect(baseEventClassNames({ colorIndex: 3 })).toEqual([
        "o_event",
        "o_calendar_color_3",
    ]);
    expect(baseEventClassNames({ colorIndex: "#fff" })).toEqual(["o_event"]);
    expect(
        baseEventClassNames({ colorIndex: false, isHatched: true, isStriked: true }),
    ).toEqual(["o_event", "o_calendar_color_0", "o_event_hatched", "o_event_striked"]);
});
