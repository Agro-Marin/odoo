// @ts-check

import { luxon } from "@web/core/l10n/luxon";
import { beforeEach, expect, test } from "@odoo/hoot";
import { animationFrame, queryAllTexts, queryFirst, queryRect } from "@odoo/hoot-dom";
import { runAllTimers } from "@odoo/hoot-mock";
import {
    mockService,
    mountWithCleanup,
    preloadFullCalendar,
} from "@web/../tests/web_test_helpers";
import { CallbackRecorder } from "@web/core/action_hook";
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
    await mountWithCleanup(CalendarCommonRenderer, {
        props: { ...FAKE_PROPS, ...props },
        target,
    });
}

preloadFullCalendar();
beforeEach(() => {
    // Upstream uses ``"UTC+1"``, but Luxon turns that into a
    // ``FixedOffsetZone`` whose name (``"UTC+1"``) is rejected by
    // ``new Intl.DateTimeFormat({ timeZone })`` — FullCalendar reads
    // ``zone.name`` and fails to mount. ``"Africa/Algiers"`` is the
    // canonical IANA zone that stays UTC+1 year-round (no DST since
    // 1981): it satisfies both FullCalendar's IANA-name requirement and
    // the millisecond assertions in this file, which assume
    // ``DEFAULT_DATE`` resolves to start-of-day at UTC+1 regardless of
    // month. ``Europe/Brussels`` would switch to UTC+2 (CEST) in July
    // and break ``record.start.valueOf()`` comparisons by one hour.
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
    // v7's timegrid week label is split between the outer cell
    // (carrying our injected ``fc-week-number`` class via
    // ``weekNumberHeaderClass``) and an inner generic ``<div>`` — both
    // inherit the ``aria-label="Week N"`` attribute.  The visible /
    // tested element is the outer ``.fc-week-number``.
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
    // v7 hashes class names, but ``viewDidMount`` in
    // ``calendar_common_renderer.js`` re-injects ``fc-scroller`` /
    // ``fc-scroller-liquid-y`` on the vertical time-grid scroller.
    // After auto-scroll, the 6am slot lane sits at the top of THAT
    // scroller — not at the top of the outer ``.fc-timeGridDay-view``,
    // which in v7 wraps the scroller plus a column header row above
    // it (and an optional all-day strip).
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
