// @ts-check

import { expect, test } from "@odoo/hoot";
import { queryAllTexts, resize } from "@odoo/hoot-dom";
import { mockTimeZone, runAllTimers } from "@odoo/hoot-mock";
import {
    mockService,
    mountWithCleanup,
    patchWithCleanup,
    preloadFullCalendar,
} from "@web/../tests/web_test_helpers";
import { CalendarYearRenderer } from "@web/views/calendar/calendar_year/calendar_year_renderer";

import { clickDate, FAKE_MODEL, selectDateRange } from "./calendar_test_helpers.js";

const FAKE_PROPS = {
    model: FAKE_MODEL,
    createRecord() {},
    deleteRecord() {},
    editRecord() {},
};

async function start(props = {}) {
    return await mountWithCleanup(CalendarYearRenderer, {
        props: { ...FAKE_PROPS, ...props },
    });
}

preloadFullCalendar();

test(`mount a CalendarYearRenderer`, async () => {
    await start();
    expect(`.fc-month-container`).toHaveCount(12);

    // v7 emits a single chunk per configured section (center: "title"); v6
    // also emitted placeholder start/end chunks, making the title chunk
    // ``:nth-child(2)``.
    expect(`.fc-toolbar-chunk .fc-toolbar-title`).toHaveCount(12);
    expect(queryAllTexts`.fc-toolbar-chunk .fc-toolbar-title`).toEqual([
        "January 2021",
        "February 2021",
        "March 2021",
        "April 2021",
        "May 2021",
        "June 2021",
        "July 2021",
        "August 2021",
        "September 2021",
        "October 2021",
        "November 2021",
        "December 2021",
    ]);

    expect(`.fc-month:eq(0) .fc-col-header-cell`).toHaveCount(7);
    expect(queryAllTexts`.fc-month:eq(0) .fc-col-header-cell`).toEqual([
        "S",
        "M",
        "T",
        "W",
        "T",
        "F",
        "S",
    ]);

    // check showNonCurrentDates
    expect(`:not(.fc-day-disabled) > * > * > .fc-daygrid-day-number`).toHaveCount(365);
});

test.tags("desktop");
test(`display events`, async () => {
    mockService("popover", () => ({
        add(target, component, props) {
            expect.step(`${props.date.toISODate()} ${props.records[0].title}`);
            return () => {};
        },
    }));

    await start({
        createRecord(record) {
            expect.step(
                `${record.start.toISODate()} allDay:${record.isAllDay} no event`,
            );
        },
    });

    await clickDate("2021-07-15");
    expect.verifySteps(["2021-07-15 allDay:true no event"]);
    await clickDate("2021-07-16");
    expect.verifySteps(["2021-07-16 1 day, all day in July"]);
    await clickDate("2021-07-17");
    expect.verifySteps(["2021-07-17 allDay:true no event"]);
    await clickDate("2021-07-18");
    expect.verifySteps(["2021-07-18 3 days, all day in July"]);
    await clickDate("2021-07-19");
    expect.verifySteps(["2021-07-19 3 days, all day in July"]);
    await clickDate("2021-07-20");
    expect.verifySteps(["2021-07-20 3 days, all day in July"]);
    await clickDate("2021-07-21");
    expect.verifySteps(["2021-07-21 allDay:true no event"]);
    await clickDate("2021-06-28");
    expect.verifySteps(["2021-06-28 allDay:true no event"]);
    await clickDate("2021-06-29");
    expect.verifySteps(["2021-06-29 Over June and July"]);
    await clickDate("2021-06-30");
    expect.verifySteps(["2021-06-30 Over June and July"]);
    await clickDate("2021-07-01");
    expect.verifySteps(["2021-07-01 Over June and July"]);
    await clickDate("2021-07-02");
    expect.verifySteps(["2021-07-02 Over June and July"]);
    await clickDate("2021-07-03");
    expect.verifySteps(["2021-07-03 Over June and July"]);
    await clickDate("2021-07-04");
    expect.verifySteps(["2021-07-04 allDay:true no event"]);
});

test.tags("desktop");
test(`select a range of date`, async () => {
    await start({
        createRecord({ isAllDay, start, end }) {
            expect.step("create");
            expect(isAllDay).toBe(true);
            expect(start.toSQL()).toBe("2021-07-02 00:00:00.000 +01:00");
            expect(end.toSQL()).toBe("2021-07-05 00:00:00.000 +01:00");
        },
    });
    await selectDateRange("2021-07-02", "2021-07-05");
    expect.verifySteps(["create"]);
});

test(`display correct column header for days, independent of the timezone`, async () => {
    // Regression test: when the system tz is somewhere in a negative GMT (in our example Alaska)
    // the day headers of a months were incorrectly set. (S S M T W T F) instead of (S M T W T F S)
    // if the first day of the week is Sunday.
    mockTimeZone(-9);
    await start();
    expect(queryAllTexts`.fc-month:eq(0) .fc-col-header-cell`).toEqual([
        "S",
        "M",
        "T",
        "W",
        "T",
        "F",
        "S",
    ]);
});

test("remove row when no day of current month", async () => {
    await start();
    expect(".fc-day-other, .fc-day-disabled").toHaveCount(76);
});

test("per-month anchor is offset-less so it doesn't drift in a fixed-offset zone", async () => {
    // In a fixed-offset ("marker") zone, an offset-bearing anchor ISO would be
    // re-derived by FullCalendar and land on the previous day, mis-anchoring the
    // mini month (the year view previously used ``date.toISO()``). The anchor
    // must be emitted as bare wall-clock time, exactly like CalendarCommonRenderer.
    mockTimeZone(2);
    const renderer = await start();
    // FAKE_MODEL.date is 2021-07-16T08:00:00.
    expect(renderer.getDateWithMonth("July")).toBe("2021-07-16T08:00:00");
    expect(renderer.getDateWithMonth("January")).toBe("2021-01-16T08:00:00");
    // No trailing offset or Z suffix on the base initialDate either.
    expect(renderer.options.initialDate).toBe("2021-07-16T08:00:00");
});

test("a window resize updates the view height with a single layout pass", async () => {
    patchWithCleanup(CalendarYearRenderer.prototype, {
        updateSize() {
            expect.step("updateSize");
            return super.updateSize();
        },
    });
    const renderer = await start();
    // Mount: one sizing pass from the render effect.
    expect.verifySteps(["updateSize"]);
    await resize({ height: 500 });
    await runAllTimers();
    // One resize event = one layout update (the root height is shared by all
    // 12 mini calendars; there used to be a 12x fan-out of identical calls).
    expect.verifySteps(["updateSize"]);
    expect(renderer.rootRef.el.style.height).toBe(
        `${window.innerHeight - renderer.rootRef.el.getBoundingClientRect().top}px`,
    );
});
