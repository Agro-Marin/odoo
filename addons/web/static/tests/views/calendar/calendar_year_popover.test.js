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

    const group = (startOffset, endOffset, title) => ({
        title,
        start: DEFAULT_DATE.plus({ days: startOffset }),
        end: DEFAULT_DATE.plus({ days: endOffset }),
        records: [],
    });

    const makeGroups = () => [
        group(0, 0, "A"),
        group(2, 2, "B"),
        group(0, 3, "C"),
        group(1, 2, "D"),
        group(1, 5, "E"),
    ];

    const expected = ["A", "B", "C", "D", "E"];
    const titles = (groups) =>
        popover.getSortedRecordGroups(groups).map((g) => g.title);

    expect(titles(makeGroups())).toEqual(expected);
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
