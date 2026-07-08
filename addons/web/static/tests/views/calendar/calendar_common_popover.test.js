// @ts-check

import { describe, expect, getFixture, test } from "@odoo/hoot";
import { click } from "@odoo/hoot-dom";
import { mountWithCleanup } from "@web/../tests/web_test_helpers";
import { CalendarCommonPopover } from "@web/views/calendar/calendar_common/calendar_common_popover";

import { DEFAULT_DATE, FAKE_MODEL } from "./calendar_test_helpers.js";

describe.current.tags("desktop");

const FAKE_RECORD = {
    id: 5,
    title: "Meeting",
    isAllDay: false,
    start: DEFAULT_DATE,
    end: DEFAULT_DATE.plus({ hours: 3, minutes: 15 }),
    colorIndex: 0,
    isTimeHidden: false,
    rawRecord: {
        name: "Meeting",
        description: "<p>Test description</p>",
    },
};

const FAKE_PROPS = {
    model: FAKE_MODEL,
    record: FAKE_RECORD,
    createRecord() {},
    deleteRecord() {},
    editRecord() {},
    close() {},
};

async function start(props = {}) {
    await mountWithCleanup(CalendarCommonPopover, {
        props: { ...FAKE_PROPS, ...props },
    });
}

test(`mount a CalendarCommonPopover`, async () => {
    await start();
    expect(`.popover-header`).toHaveCount(1);
    expect(`.popover-header`).toHaveText("Meeting");
    expect(`.list-group`).toHaveCount(2);
    expect(`.list-group.o_cw_popover_fields_secondary`).toHaveCount(1);
    expect(
        `.list-group.o_cw_popover_fields_secondary div[name="description"]`,
    ).toHaveClass("text-wrap");
    expect(`.card-footer .o_cw_popover_edit`).toHaveCount(1);
    expect(`.card-footer .o_cw_popover_delete`).toHaveCount(1);
});

test(`date duration: is all day and is same day`, async () => {
    await start({
        record: { ...FAKE_RECORD, isAllDay: true, isTimeHidden: true },
    });
    expect(`.list-group:eq(0)`).toHaveText("July 16, 2021");
});

test(`date duration: is all day and two days duration`, async () => {
    await start({
        record: {
            ...FAKE_RECORD,
            end: DEFAULT_DATE.plus({ days: 1 }),
            isAllDay: true,
            isTimeHidden: true,
        },
    });
    expect(`.list-group:eq(0)`).toHaveText("July 16-17, 2021 2 days");
});

test(`time duration: 1 hour diff`, async () => {
    await start({
        record: { ...FAKE_RECORD, end: DEFAULT_DATE.plus({ hours: 1 }) },
        model: { ...FAKE_MODEL, isDateHidden: true },
    });
    expect(`.list-group:eq(0)`).toHaveText("08:00 - 09:00 (1 hour)");
});

test(`time duration: 2 hours diff`, async () => {
    await start({
        record: { ...FAKE_RECORD, end: DEFAULT_DATE.plus({ hours: 2 }) },
        model: { ...FAKE_MODEL, isDateHidden: true },
    });
    expect(`.list-group:eq(0)`).toHaveText("08:00 - 10:00 (2 hours)");
});

test(`time duration: 1 minute diff`, async () => {
    await start({
        record: { ...FAKE_RECORD, end: DEFAULT_DATE.plus({ minutes: 1 }) },
        model: { ...FAKE_MODEL, isDateHidden: true },
    });
    expect(`.list-group:eq(0)`).toHaveText("08:00 - 08:01 (1 minute)");
});

test(`time duration: 2 minutes diff`, async () => {
    await start({
        record: { ...FAKE_RECORD, end: DEFAULT_DATE.plus({ minutes: 2 }) },
        model: { ...FAKE_MODEL, isDateHidden: true },
    });
    expect(`.list-group:eq(0)`).toHaveText("08:00 - 08:02 (2 minutes)");
});

test(`time duration: 3 hours and 15 minutes diff`, async () => {
    await start({
        model: { ...FAKE_MODEL, isDateHidden: true },
    });
    expect(`.list-group:eq(0)`).toHaveText("08:00 - 11:15 (3 hours, 15 minutes)");
});

test(`isDateHidden is true`, async () => {
    await start({
        model: { ...FAKE_MODEL, isDateHidden: true },
    });
    expect(`.list-group:eq(0)`).toHaveText("08:00 - 11:15 (3 hours, 15 minutes)");
});

test(`isDateHidden is false`, async () => {
    await start({
        model: { ...FAKE_MODEL, isDateHidden: false },
    });
    expect(`.list-group:eq(0)`).toHaveText(
        "July 16, 2021\n08:00 - 11:15 (3 hours, 15 minutes)",
    );
});

test(`isTimeHidden is true`, async () => {
    await start({
        record: { ...FAKE_RECORD, isTimeHidden: true },
    });
    expect(`.list-group:eq(0)`).toHaveText("July 16, 2021");
});

test(`isTimeHidden is false`, async () => {
    await start({
        record: { ...FAKE_RECORD, isTimeHidden: false },
    });
    expect(`.list-group:eq(0)`).toHaveText(
        "July 16, 2021\n08:00 - 11:15 (3 hours, 15 minutes)",
    );
});

test(`canDelete is true`, async () => {
    await start({
        model: { ...FAKE_MODEL, canDelete: true },
    });
    expect(`.o_cw_popover_delete`).toHaveCount(1);
});

test(`canDelete is false`, async () => {
    await start({
        model: { ...FAKE_MODEL, canDelete: false },
    });
    expect(`.o_cw_popover_delete`).toHaveCount(0);
});

test(`click on delete button`, async () => {
    await start({
        model: { ...FAKE_MODEL, canDelete: true },
        deleteRecord: () => expect.step("delete"),
    });
    await click(`.o_cw_popover_delete`);
    expect.verifySteps(["delete"]);
});

test(`click on edit button`, async () => {
    await start({
        editRecord: () => expect.step("edit"),
    });
    await click(`.o_cw_popover_edit`);
    expect.verifySteps(["edit"]);
});

test(`pointerdown outside the calendar keeps its default (input focus not suppressed)`, async () => {
    await start();
    // An input in unrelated UI (e.g. the side-panel autocomplete) must keep its
    // default behavior so the first click focuses it — the popover's window
    // pointerdown guard used to preventDefault on every outside pointerdown.
    const input = document.createElement("input");
    getFixture().appendChild(input);
    const ev = new PointerEvent("pointerdown", { bubbles: true, cancelable: true });
    input.dispatchEvent(ev);
    expect(ev.defaultPrevented).toBe(false);
});

test(`pointerdown on another calendar event is intercepted (closes popover)`, async () => {
    await start();
    const widget = document.createElement("div");
    widget.className = "o_calendar_widget";
    widget.innerHTML = `<div class="fc-event" data-event-id="999"></div>`;
    getFixture().appendChild(widget);
    const ev = new PointerEvent("pointerdown", { bubbles: true, cancelable: true });
    widget.querySelector(".fc-event").dispatchEvent(ev);
    expect(ev.defaultPrevented).toBe(true);
});

test(`pointerdown on the popover's own event keeps its default (drag & drop)`, async () => {
    await start(); // FAKE_RECORD.id === 5
    const widget = document.createElement("div");
    widget.className = "o_calendar_widget";
    widget.innerHTML = `<div class="fc-event" data-event-id="5"></div>`;
    getFixture().appendChild(widget);
    const ev = new PointerEvent("pointerdown", { bubbles: true, cancelable: true });
    widget.querySelector(".fc-event").dispatchEvent(ev);
    expect(ev.defaultPrevented).toBe(false);
});
