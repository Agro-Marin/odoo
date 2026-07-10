// @ts-check

import { describe, expect, test } from "@odoo/hoot";
import { queryAllTexts } from "@odoo/hoot-dom";
import {
    contains,
    mountWithCleanup,
    preloadFullCalendar,
} from "@web/../tests/web_test_helpers";
import { CalendarYearPopover } from "@web/views/calendar/calendar_year/calendar_year_popover";

import { DEFAULT_DATE, FAKE_MODEL } from "./calendar_test_helpers.js";

describe.current.tags("desktop");

const FAKE_RECORDS = [
    {
        id: 1,
        start: DEFAULT_DATE,
        end: DEFAULT_DATE,
        isAllDay: true,
        title: "R1",
    },
    {
        id: 2,
        start: DEFAULT_DATE.set({ hours: 14 }),
        end: DEFAULT_DATE.set({ hours: 16 }),
        isAllDay: false,
        title: "R2",
    },
    {
        id: 3,
        start: DEFAULT_DATE.minus({ days: 1 }),
        end: DEFAULT_DATE.plus({ days: 1 }),
        isAllDay: true,
        title: "R3",
    },
    {
        id: 4,
        start: DEFAULT_DATE.minus({ days: 3 }),
        end: DEFAULT_DATE.plus({ days: 1 }),
        isAllDay: true,
        title: "R4",
    },
    {
        id: 5,
        start: DEFAULT_DATE.minus({ days: 1 }),
        end: DEFAULT_DATE.plus({ days: 3 }),
        isAllDay: true,
        title: "R5",
    },
];

const FAKE_PROPS = {
    model: FAKE_MODEL,
    date: DEFAULT_DATE,
    records: FAKE_RECORDS,
    createRecord() {},
    deleteRecord() {},
    editRecord() {},
    close() {},
};

async function start(props = {}) {
    return mountWithCleanup(CalendarYearPopover, {
        props: { ...FAKE_PROPS, ...props },
    });
}

preloadFullCalendar();

test(`canCreate is true`, async () => {
    await start({
        model: { ...FAKE_MODEL, canCreate: true },
    });
    expect(`.o_cw_popover_create`).toHaveCount(1);
});

test(`canCreate is false`, async () => {
    await start({
        model: { ...FAKE_MODEL, canCreate: false },
    });
    expect(`.o_cw_popover_create`).toHaveCount(0);
});

test(`click on create button`, async () => {
    await start({
        createRecord: () => expect.step("create"),
        model: { ...FAKE_MODEL, canCreate: true },
    });
    expect(`.o_cw_popover_create`).toHaveCount(1);

    await contains(`.o_cw_popover_create`).click();
    expect.verifySteps(["create"]);
});

test(`group records`, async () => {
    await start();
    expect(`.o_cw_body > div`).toHaveCount(4);
    expect(`.o_cw_body > a`).toHaveCount(1);
    expect(queryAllTexts`.o_cw_body > div`).toEqual([
        "July 16, 2021\nR1\n14:00\nR2",
        "July 13-17, 2021\nR4",
        "July 15-17, 2021\nR3",
        "July 15-19, 2021\nR5",
    ]);
    expect(`.o_cw_body`).toHaveText(
        "July 16, 2021\nR1\n14:00\nR2\nJuly 13-17, 2021\nR4\nJuly 15-17, 2021\nR3\nJuly 15-19, 2021\nR5\n Create",
    );
});

test(`click on record`, async () => {
    await start({
        records: [FAKE_RECORDS[3]],
        editRecord: () => expect.step("edit"),
    });
    expect(`.o_cw_body a.o_cw_popover_link`).toHaveCount(1);

    await contains(`.o_cw_body a.o_cw_popover_link`).click();
    expect.verifySteps(["edit"]);
});

test(`getSortedRecordGroups is a valid total order`, async () => {
    const popover = await start();

    /** build a group-like object with luxon start/end from day offsets */
    const group = (startOffset, endOffset, title) => ({
        title,
        start: DEFAULT_DATE.plus({ days: startOffset }),
        end: DEFAULT_DATE.plus({ days: endOffset }),
        records: [],
    });

    // Two same-day groups (A, B) and three multi-day groups (C, D, E). The old
    // comparator returned MIN_SAFE_INTEGER for a same-day `a` and
    // MAX_SAFE_INTEGER for a same-day `b`, so comparing two same-day groups was
    // asymmetric and the result depended on input order.
    const makeGroups = () => [
        group(0, 0, "A"), // same day
        group(2, 2, "B"), // same day
        group(0, 3, "C"), // multi-day, starts day 0
        group(1, 2, "D"), // multi-day, starts day 1, ends day 2
        group(1, 5, "E"), // multi-day, starts day 1, ends day 5
    ];

    const expected = ["A", "B", "C", "D", "E"];
    const titles = (groups) =>
        popover.getSortedRecordGroups(groups).map((g) => g.title);

    // Same-day groups first, then multi-day sorted by start, then end.
    expect(titles(makeGroups())).toEqual(expected);
    // Total order: the sorted result is independent of the input order.
    expect(titles(makeGroups().reverse())).toEqual(expected);
    expect(
        titles([
            makeGroups()[3],
            makeGroups()[0],
            makeGroups()[4],
            makeGroups()[1],
            makeGroups()[2],
        ]),
    ).toEqual(expected);
});
