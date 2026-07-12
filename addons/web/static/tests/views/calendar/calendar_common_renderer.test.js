// @ts-check

import { beforeEach, expect, test } from "@odoo/hoot";
import { animationFrame, queryAllTexts, queryFirst, queryRect } from "@odoo/hoot-dom";
import { mockDate, runAllTimers } from "@odoo/hoot-mock";
import {
    mockService,
    mountWithCleanup,
    preloadFullCalendar,
} from "@web/../tests/web_test_helpers";
import { CallbackRecorder } from "@web/core/action_hook";
import { luxon } from "@web/core/l10n/luxon";
import { CalendarCommonRenderer } from "@web/views/calendar/calendar_common/calendar_common_renderer";

import {
    clickAllDaySlot,
    clickEvent,
    DEFAULT_DATE,
    FAKE_MODEL,
    selectTimeRange,
} from "./calendar_test_helpers.js";

const FAKE_PROPS = {
    model: FAKE_MODEL,
    createRecord() {},
    deleteRecord() {},
    editRecord() {},
    callbackRecorder: new CallbackRecorder(),
    onSquareSelection() {},
    cleanSquareSelection() {},
};

async function start(props = {}, target) {
    return await mountWithCleanup(CalendarCommonRenderer, {
        props: { ...FAKE_PROPS, ...props },
        target,
    });
}

preloadFullCalendar();
beforeEach(() => {
    // "UTC+1" makes Luxon produce a FixedOffsetZone name that
    // Intl.DateTimeFormat rejects, breaking FullCalendar's mount. Use
    // "Africa/Algiers" (UTC+1 year-round, no DST) instead of e.g.
    // Europe/Brussels, which would be UTC+2 (CEST) in July and break the
    // millisecond assertions below by an hour.
    luxon.Settings.defaultZone = "Africa/Algiers";
});

test(`mount a CalendarCommonRenderer`, async () => {
    await start();
    expect(`.o_calendar_widget.fc`).toHaveCount(1);
});

test(`Day: mount a CalendarCommonRenderer`, async () => {
    await start({ model: { ...FAKE_MODEL, scale: "day" } });
    expect(`.o_calendar_widget.fc .fc-timeGridDay-view`).toHaveCount(1);
});

test(`Week: mount a CalendarCommonRenderer`, async () => {
    await start({ model: { ...FAKE_MODEL, scale: "week" } });
    expect(`.o_calendar_widget.fc .fc-timeGridWeek-view`).toHaveCount(1);
});

test(`Month: mount a CalendarCommonRenderer`, async () => {
    await start({ model: { ...FAKE_MODEL, scale: "month" } });
    expect(`.o_calendar_widget.fc .fc-dayGridMonth-view`).toHaveCount(1);
});

test(`Day: check week number`, async () => {
    await start({ model: { ...FAKE_MODEL, scale: "day" } });
    // The visible/tested element is the outer ``.fc-week-number`` cell
    // (carrying our injected class); an inner generic div shares its label.
    expect(`.fc-week-number`).toHaveCount(1);
    expect(`.fc-week-number`).toHaveText(/(Week )?28/);
});

test(`Day: check date`, async () => {
    await start({ model: { ...FAKE_MODEL, scale: "day" } });
    expect(`.fc-col-header-cell.fc-day`).toHaveCount(1);
    expect(`.fc-col-header-cell.fc-day:eq(0) .o_cw_day_name`).toHaveText("Friday");
    expect(`.fc-col-header-cell.fc-day:eq(0) .o_cw_day_number`).toHaveText("16");
});

test(`Day: click all day slot`, async () => {
    await start({
        model: { ...FAKE_MODEL, scale: "day" },
        createRecord(record) {
            expect.step("create");
            expect(record.isAllDay).toBe(true);
            expect(record.start.valueOf()).toBe(DEFAULT_DATE.startOf("day").valueOf());
        },
    });
    await clickAllDaySlot("2021-07-16");
    expect.verifySteps(["create"]);
});

test.tags("desktop");
test(`Day: select range`, async () => {
    await start({
        model: { ...FAKE_MODEL, scale: "day" },
        createRecord(record) {
            expect.step("create");
            expect(record.isAllDay).toBe(false);
            expect(record.start.valueOf()).toBe(
                luxon.DateTime.local(2021, 7, 16, 8, 0).valueOf(),
            );
            expect(record.end.valueOf()).toBe(
                luxon.DateTime.local(2021, 7, 16, 10, 0).valueOf(),
            );
        },
    });
    await selectTimeRange("2021-07-16 08:00:00", "2021-07-16 10:00:00");
    expect.verifySteps(["create"]);
});

test(`Day: check event`, async () => {
    await start({ model: { ...FAKE_MODEL, scale: "day" } });
    expect(`.o_event`).toHaveCount(1);
    expect(`.o_event`).toHaveAttribute("data-event-id", "1");
});

test.tags("desktop");
test(`Day: click on event`, async () => {
    mockService("popover", () => ({
        add(target, component, { record }) {
            expect.step("popover");
            expect(record.id).toBe(1);
            return () => {};
        },
    }));
    await start({ model: { ...FAKE_MODEL, scale: "day" } });
    await clickEvent(1);
    await runAllTimers();
    expect.verifySteps(["popover"]);
});

test(`Week: check week number`, async () => {
    await start({ model: { ...FAKE_MODEL, scale: "week" } });
    // v7 dropped the v6 ``fc-scrollgrid-section-header`` /
    // ``fc-timegrid-axis-cushion`` containers; the week-label cell is
    // emitted with the ``fc-week-number`` class directly.
    expect(`.fc-week-number`).toHaveCount(1);
    expect(`.fc-week-number`).toHaveText(/(Week )?28/);
});

test(`Week: check dates`, async () => {
    await start({ model: { ...FAKE_MODEL, scale: "week" } });
    expect(`.fc-col-header-cell.fc-day`).toHaveCount(7);
    expect(queryAllTexts(`.fc-col-header-cell .o_cw_day_name`)).toEqual([
        "Sun",
        "Mon",
        "Tue",
        "Wed",
        "Thu",
        "Fri",
        "Sat",
    ]);
    expect(queryAllTexts`.fc-col-header-cell .o_cw_day_number`).toEqual([
        "11",
        "12",
        "13",
        "14",
        "15",
        "16",
        "17",
    ]);
});

test(`Day: automatically scroll to 6am`, async () => {
    await mountWithCleanup(`<div class="scrollable" style="height: 500px;"/>`);
    await start({ model: { ...FAKE_MODEL, scale: "day" } }, queryFirst(`.scrollable`));
    // FC v7's ``applyTimeScroll`` defers via ``afterSize`` →
    // ``requestAnimationFrame``. Flush one RAF so the auto-scroll
    // lands before we assert position.
    await animationFrame();
    // v7 hashes class names, but ``viewDidMount`` re-injects
    // ``fc-scroller-liquid-y`` on the vertical time-grid scroller; after
    // auto-scroll the 6am slot sits at the top of THAT scroller, not of the
    // outer ``.fc-timeGridDay-view`` (which also wraps a header row).
    const scrollerY = queryRect(`.fc-scroller-liquid-y`).y;
    const slotY = queryRect(`[data-time="06:00:00"]:eq(0)`).y;
    expect(Math.abs(slotY - scrollerY)).toBeLessThan(2);
});

test(`Week: automatically scroll to 6am`, async () => {
    await mountWithCleanup(`<div class="scrollable" style="height: 500px;"/>`);
    await start({ model: { ...FAKE_MODEL, scale: "week" } }, queryFirst(`.scrollable`));
    await runAllTimers();
    await animationFrame();
    // See Day-version comment: ``.fc-scroller-liquid-y`` is the
    // vertical time-grid scroller, tagged by ``viewDidMount`` so
    // tests can target it stably across FC v7 hash changes.
    const scrollerY = queryRect(`.fc-scroller-liquid-y`).y;
    const slotY = queryRect(`[data-time="06:00:00"]:eq(0)`).y;
    expect(Math.abs(slotY - scrollerY)).toBeLessThan(2);
});

test("Month: remove row when no day of current month", async () => {
    await start({ model: { ...FAKE_MODEL, scale: "month" } });
    expect(".fc-day-other, .fc-day-disabled").toHaveCount(4);
});

test(`o_past_event: an all-day event on its last day today is not styled past`, async () => {
    // All-day records normalize their end to start-of-day, so a single-day
    // all-day event today has end === midnight of today. It must not be greyed
    // out until the day is actually over (start of the following day).
    mockDate("2021-07-16T12:00:00");
    const today = luxon.DateTime.now().startOf("day");
    const model = {
        ...FAKE_MODEL,
        records: {
            10: {
                id: 10,
                title: "all day today",
                isAllDay: true,
                start: today,
                end: today,
            },
            11: {
                id: 11,
                title: "all day yesterday",
                isAllDay: true,
                start: today.minus({ days: 1 }),
                end: today.minus({ days: 1 }),
            },
            12: {
                id: 12,
                title: "timed, already ended today",
                isAllDay: false,
                start: today.plus({ hours: 8 }),
                end: today.plus({ hours: 9 }),
            },
        },
    };
    const renderer = await start({ model });
    // FIX: today's all-day event is not past.
    expect(renderer.eventClassNames({ event: { id: 10 } })).not.toInclude(
        "o_past_event",
    );
    // Regression guards: a genuinely finished event is still styled past.
    expect(renderer.eventClassNames({ event: { id: 11 } })).toInclude("o_past_event");
    expect(renderer.eventClassNames({ event: { id: 12 } })).toInclude("o_past_event");
});

test(`isSelectionAllowed: a timed selection ending exactly at midnight is allowed`, async () => {
    const renderer = await start();
    // Build Dates with native local-tz setters: isSelectionAllowed compares via
    // local Date methods, but a bare ``new Date(y, m, d, h)`` is interpreted as
    // UTC by Hoot's MockDate and would drift under a non-UTC runtime.
    const atLocal = (year, monthIndex, day, hour) => {
        const d = new Date();
        d.setFullYear(year, monthIndex, day);
        d.setHours(hour, 0, 0, 0);
        return d;
    };
    // 23:00 -> 24:00 rolls the end over to 00:00 of the next day; the last slot
    // of a day must still be selectable.
    expect(
        renderer.isSelectionAllowed({
            allDay: false,
            start: atLocal(2021, 6, 16, 23),
            end: atLocal(2021, 6, 17, 0),
        }),
    ).toBe(true);
    // A single-slot selection within the day stays allowed.
    expect(
        renderer.isSelectionAllowed({
            allDay: false,
            start: atLocal(2021, 6, 16, 8),
            end: atLocal(2021, 6, 16, 9),
        }),
    ).toBe(true);
    // A genuinely cross-day selection is still refused.
    expect(
        renderer.isSelectionAllowed({
            allDay: false,
            start: atLocal(2021, 6, 16, 22),
            end: atLocal(2021, 6, 17, 1),
        }),
    ).toBe(false);
});

test(`fcEventToRecord returns null when the dragged record was removed mid-interaction`, async () => {
    const renderer = await start({ model: { ...FAKE_MODEL, scale: "week" } });
    // id 9999 is not among the model's records: a reload landing mid-drag can
    // drop the record, and dereferencing existingRecord.start/.id used to throw.
    expect(
        renderer.fcEventToRecord({
            id: 9999,
            allDay: false,
            start: new Date(2021, 6, 16, 10, 0),
            end: new Date(2021, 6, 16, 11, 0),
        }),
    ).toBe(null);
    // A live record (id 1) still converts normally, carrying its id back.
    expect(
        renderer.fcEventToRecord({
            id: 1,
            allDay: false,
            start: new Date(2021, 6, 16, 10, 0),
            end: new Date(2021, 6, 16, 11, 0),
        }).id,
    ).toBe(1);
});

test(`onEventDrop no-ops (and reverts) when the record vanished mid-drag`, async () => {
    let updated = false;
    let reverted = false;
    const renderer = await start({
        model: {
            ...FAKE_MODEL,
            scale: "week",
            updateRecord: () => {
                updated = true;
            },
        },
    });
    renderer.onEventDrop({
        event: {
            id: 9999,
            allDay: false,
            start: new Date(2021, 6, 16, 10, 0),
            end: new Date(2021, 6, 16, 11, 0),
        },
        revert: () => {
            reverted = true;
        },
    });
    expect(updated).toBe(false);
    expect(reverted).toBe(true);
});
