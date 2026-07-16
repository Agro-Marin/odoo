// @ts-check

import { expect, test } from "@odoo/hoot";
import { queryAllTexts, queryFirst } from "@odoo/hoot-dom";
import { mockDate, mockTimeZone } from "@odoo/hoot-mock";
import {
    defineModels,
    fields,
    models,
    mountView,
    onRpc,
    patchWithCleanup,
    preloadFullCalendar,
} from "@web/../tests/web_test_helpers";
import { IANAZone, Settings } from "@web/core/l10n/luxon";
import { getFullCalendarTimeZone } from "@web/views/calendar/hooks/full_calendar_hook";

/**
 * DST-transition coverage with a real IANA zone. The rest of the calendar
 * suite mocks fixed offsets (marker mode); these tests pin the IANA
 * passthrough path (FullCalendar `timeZone: "Europe/Brussels"`) around the
 * two European transitions:
 * - spring forward: 2024-03-31, 02:00 +01:00 -> 03:00 +02:00
 * - fall back:      2024-10-27, 03:00 +02:00 -> 02:00 +01:00
 *
 * Also pins `getFullCalendarTimeZone`'s zone classification: slash-less
 * IANA zones with working DST (CET, EET, GB, ...) must pass through by
 * name — hoot's `mockTimeZone` only accepts `Region/Location` strings, so
 * those tests patch `Settings.defaultZone` directly.
 */

class Event extends models.Model {
    name = fields.Char();
    start = fields.Datetime();
    stop = fields.Datetime();

    has_access() {
        return true;
    }

    _records = [
        // Spring-forward week (2024-03-31 .. 2024-04-06)
        {
            id: 1,
            name: "before spring switch",
            start: "2024-03-31 00:30:00", // local 01:30 (+01:00)
            stop: "2024-03-31 00:45:00",
        },
        {
            id: 2,
            name: "after spring switch, crosses UTC midnight",
            start: "2024-03-31 23:30:00", // local Apr 1st, 01:30 (+02:00)
            stop: "2024-03-31 23:45:00",
        },
        // Fall-back week (2024-10-27 .. 2024-11-02)
        {
            id: 3,
            name: "before fall switch, crosses UTC midnight",
            start: "2024-10-26 22:30:00", // local Oct 27th, 00:30 (+02:00)
            stop: "2024-10-26 22:45:00",
        },
        {
            id: 4,
            name: "after fall switch",
            start: "2024-10-27 22:30:00", // local 23:30 (+01:00)
            stop: "2024-10-27 22:45:00",
        },
        // Summer week in a slash-less IANA zone (CET -> CEST, +02:00)
        {
            id: 5,
            name: "summer CET, crosses UTC midnight",
            start: "2024-07-09 22:30:00", // local Jul 10th, 00:30 (CEST, +02:00)
            stop: "2024-07-09 22:45:00",
        },
    ];
}

defineModels([Event]);
preloadFullCalendar();

onRpc("has_group", () => true);

test("week range crossing spring-forward serializes each bound with its own offset", async () => {
    mockDate("2024-04-02T08:00:00");
    mockTimeZone("Europe/Brussels");
    onRpc("search_read", ({ kwargs }) => {
        expect.step("search_read");
        expect(kwargs.domain).toEqual([
            // End of the week is after the switch: +02:00.
            ["start", "<=", "2024-04-06 21:59:59"],
            // Start of the week is before the switch: +01:00.
            ["stop", ">=", "2024-03-30 23:00:00"],
        ]);
    });

    await mountView({
        resModel: "event",
        type: "calendar",
        arch: `<calendar date_start="start" date_stop="stop" mode="week"/>`,
    });
    expect.verifySteps(["search_read"]);
});

test("week range crossing fall-back serializes each bound with its own offset", async () => {
    mockDate("2024-10-29T08:00:00");
    mockTimeZone("Europe/Brussels");
    onRpc("search_read", ({ kwargs }) => {
        expect.step("search_read");
        expect(kwargs.domain).toEqual([
            // End of the week is after the switch: +01:00.
            ["start", "<=", "2024-11-02 22:59:59"],
            // Start of the week is before the switch: +02:00.
            ["stop", ">=", "2024-10-26 22:00:00"],
        ]);
    });

    await mountView({
        resModel: "event",
        type: "calendar",
        arch: `<calendar date_start="start" date_stop="stop" mode="week"/>`,
    });
    expect.verifySteps(["search_read"]);
});

test.tags("desktop");
test("events around spring-forward render in the local day column", async () => {
    mockDate("2024-04-02T08:00:00");
    mockTimeZone("Europe/Brussels");

    await mountView({
        resModel: "event",
        type: "calendar",
        arch: `<calendar date_start="start" date_stop="stop" mode="week"/>`,
    });

    // 00:30Z on the transition day is still +01:00: local March 31st.
    expect(
        queryFirst(`.o_event[data-event-id="1"]`).closest("[data-date]"),
    ).toHaveAttribute("data-date", "2024-03-31");
    // 23:30Z is +02:00 by then: local April 1st, NOT March 31st (a fixed
    // pre-transition offset would keep it in the March 31st column).
    expect(
        queryFirst(`.o_event[data-event-id="2"]`).closest("[data-date]"),
    ).toHaveAttribute("data-date", "2024-04-01");
});

test.tags("desktop");
test("events around fall-back render in the local day column", async () => {
    mockDate("2024-10-29T08:00:00");
    mockTimeZone("Europe/Brussels");

    await mountView({
        resModel: "event",
        type: "calendar",
        arch: `<calendar date_start="start" date_stop="stop" mode="week"/>`,
    });

    // Oct 26th 22:30Z is still +02:00: local Oct 27th 00:30 (a fixed
    // post-transition +01:00 offset would render it in the Oct 26th column,
    // outside the week).
    expect(
        queryFirst(`.o_event[data-event-id="3"]`).closest("[data-date]"),
    ).toHaveAttribute("data-date", "2024-10-27");
    // Oct 27th 22:30Z is +01:00 by then: local 23:30, same day (a fixed
    // pre-transition +02:00 offset would push it into the Oct 28th column).
    expect(
        queryFirst(`.o_event[data-event-id="4"]`).closest("[data-date]"),
    ).toHaveAttribute("data-date", "2024-10-27");
});

test.tags("desktop");
test("week header labels stay aligned across the transition", async () => {
    mockDate("2024-04-02T08:00:00");
    mockTimeZone("Europe/Brussels");

    await mountView({
        resModel: "event",
        type: "calendar",
        arch: `<calendar date_start="start" date_stop="stop" mode="week"/>`,
    });

    expect(queryAllTexts(`.fc-col-header-cell .o_cw_day_name`)).toEqual([
        "Sun",
        "Mon",
        "Tue",
        "Wed",
        "Thu",
        "Fri",
        "Sat",
    ]);
    expect(queryAllTexts(`.fc-col-header-cell .o_cw_day_number`)).toEqual([
        "31",
        "1",
        "2",
        "3",
        "4",
        "5",
        "6",
    ]);
});

test("getFullCalendarTimeZone passes slash-less IANA zones through by name", async () => {
    // Zone classification must go by Luxon zone TYPE, not name shape: CET
    // is a real IANA zone with working DST. A name-shape check (`includes("/")`)
    // used to drop it into the fixed-offset path, freezing the January-1970
    // offset (Etc/GMT-1) for the whole year.
    patchWithCleanup(Settings, { defaultZone: IANAZone.create("CET") });
    expect(getFullCalendarTimeZone()).toBe("CET");
});

test("getFullCalendarTimeZone accepts a system zone resolving to an IANA name", async () => {
    // The system zone's name is Intl's resolved identifier — pass it through
    // when Intl can resolve it, even without a slash. Minimal Zone-like stub:
    // the function only reads `type` / `name` / `offset`.
    patchWithCleanup(Settings, {
        defaultZone: { type: "system", name: "CET", offset: () => 120, isValid: true },
    });
    expect(getFullCalendarTimeZone()).toBe("CET");
});

test("getFullCalendarTimeZone maps fixed offsets to inverted POSIX Etc/GMT names", async () => {
    // `mockTimeZone(+2)` installs a FixedOffsetZone(+120') as defaultZone
    // (see tests/_framework/patch_test_helpers.js) — not an IANA zone, so it
    // takes the POSIX path with the sign inverted: UTC+2 -> Etc/GMT-2.
    mockTimeZone(+2);
    expect(getFullCalendarTimeZone()).toBe("Etc/GMT-2");
    mockTimeZone(-7);
    expect(getFullCalendarTimeZone()).toBe("Etc/GMT+7");
});

test.tags("desktop");
test("summer events in a slash-less DST zone render in the local day column", async () => {
    mockDate("2024-07-10T08:00:00");
    // hoot's `mockTimeZone` rejects slash-less names; install IANAZone("CET")
    // the same way the framework's onTimeZoneChange hook would.
    patchWithCleanup(Settings, { defaultZone: IANAZone.create("CET") });

    await mountView({
        resModel: "event",
        type: "calendar",
        arch: `<calendar date_start="start" date_stop="stop" mode="week"/>`,
    });

    // Jul 9th 22:30Z is CEST (+02:00): local Jul 10th, 00:30. The frozen
    // January offset (Etc/GMT-1) would render it at 23:30 in the Jul 9th
    // column, one hour (and one day) early.
    expect(
        queryFirst(`.o_event[data-event-id="5"]`).closest("[data-date]"),
    ).toHaveAttribute("data-date", "2024-07-10");
});
