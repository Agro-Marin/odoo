// @ts-check

import {
    click,
    drag,
    edit,
    hover,
    queryAll,
    queryFirst,
    queryRect,
} from "@odoo/hoot-dom";
import { advanceFrame, advanceTime, animationFrame } from "@odoo/hoot-mock";
import { EventBus } from "@odoo/owl";
import {
    contains,
    getMockEnv,
    swipeLeft,
    swipeRight,
} from "@web/../tests/web_test_helpers";
import { luxon } from "@web/core/l10n/luxon";
import { createElement } from "@web/core/utils/dom/xml";
import { CalendarModel } from "@web/views/calendar/calendar_model";
import { parseFieldNode } from "@web/views/field_arch";

export const DEFAULT_DATE = luxon.DateTime.local(2021, 7, 16, 8, 0, 0, 0);

export const FAKE_RECORDS = {
    1: {
        id: 1,
        title: "1 day, all day in July",
        start: DEFAULT_DATE,
        isAllDay: true,
        end: DEFAULT_DATE,
    },
    2: {
        id: 2,
        title: "3 days, all day in July",
        start: DEFAULT_DATE.plus({ days: 2 }),
        isAllDay: true,
        end: DEFAULT_DATE.plus({ days: 4 }),
    },
    3: {
        id: 3,
        title: "1 day, all day in June",
        start: DEFAULT_DATE.plus({ months: -1 }),
        isAllDay: true,
        end: DEFAULT_DATE.plus({ months: -1 }),
    },
    4: {
        id: 4,
        title: "3 days, all day in June",
        start: DEFAULT_DATE.plus({ months: -1, days: 2 }),
        isAllDay: true,
        end: DEFAULT_DATE.plus({ months: -1, days: 4 }),
    },
    5: {
        id: 5,
        title: "Over June and July",
        start: DEFAULT_DATE.startOf("month").plus({ days: -2 }),
        isAllDay: true,
        end: DEFAULT_DATE.startOf("month").plus({ days: 2 }),
    },
};

export const FAKE_FILTER_SECTIONS = [
    {
        label: "Attendees",
        fieldName: "partner_ids",
        avatar: {
            model: "res.partner",
            field: "avatar_128",
        },
        hasAvatar: true,
        write: {
            model: "filter_partner",
            field: "partner_id",
        },
        canAddFilter: true,
        filters: [
            {
                type: "user",
                label: "Mitchell Admin",
                active: true,
                value: 3,
                colorIndex: 3,
                recordId: null,
                canRemove: false,
                hasAvatar: true,
            },
            {
                type: "record",
                label: "Brandon Freeman",
                active: true,
                value: 4,
                colorIndex: 4,
                recordId: 1,
                canRemove: true,
                hasAvatar: true,
            },
            {
                type: "record",
                label: "Marc Demo",
                active: false,
                value: 6,
                colorIndex: 6,
                recordId: 2,
                canRemove: true,
                hasAvatar: true,
            },
        ],
    },
    {
        label: "Users",
        fieldName: "user_id",
        avatar: {
            model: null,
            field: null,
        },
        hasAvatar: false,
        write: {
            model: null,
            field: null,
        },
        canAddFilter: false,
        filters: [
            {
                type: "record",
                label: "Brandon Freeman",
                active: false,
                value: 1,
                colorIndex: false,
                recordId: null,
                canRemove: true,
                hasAvatar: true,
            },
            {
                type: "record",
                label: "Marc Demo",
                active: false,
                value: 2,
                colorIndex: false,
                recordId: null,
                canRemove: true,
                hasAvatar: true,
            },
        ],
    },
];

export const FAKE_FIELDS = {
    id: { string: "Id", type: "integer" },
    user_id: { string: "User", type: "many2one", relation: "user", default: -1 },
    partner_id: {
        string: "Partner",
        type: "many2one",
        relation: "partner",
        related: "user_id.partner_id",
        default: 1,
    },
    name: { string: "Name", type: "char" },
    description: { string: "Description", type: "html" },
    start_date: { string: "Start Date", type: "date" },
    stop_date: { string: "Stop Date", type: "date" },
    start: { string: "Start Datetime", type: "datetime" },
    stop: { string: "Stop Datetime", type: "datetime" },
    delay: { string: "Delay", type: "float" },
    allday: { string: "Is All Day", type: "boolean" },
    partner_ids: {
        string: "Attendees",
        type: "one2many",
        relation: "partner",
        default: [[6, 0, [1]]],
    },
    type: { string: "Type", type: "integer" },
    event_type_id: { string: "Event Type", type: "many2one", relation: "event_type" },
    color: { string: "Color", type: "integer", related: "event_type_id.color" },
};

export const FAKE_MODEL = {
    bus: new EventBus(),
    canCreate: true,
    canDelete: true,
    canEdit: true,
    date: DEFAULT_DATE,
    fieldMapping: {
        date_start: "start_date",
        date_stop: "stop_date",
        date_delay: "delay",
        all_day: "allday",
        color: "color",
    },
    fieldNames: ["start_date", "stop_date", "color", "delay", "allday", "user_id"],
    fields: FAKE_FIELDS,
    filterSections: FAKE_FILTER_SECTIONS,
    firstDayOfWeek: 0,
    isDateHidden: false,
    isTimeHidden: false,
    hasAllDaySlot: true,
    hasEditDialog: false,
    quickCreate: false,
    popoverFieldNodes: {
        name: parseFieldNode(
            createElement("field", { name: "name" }),
            { event: { fields: FAKE_FIELDS } },
            "event",
            "calendar",
        ),
        description: parseFieldNode(
            createElement("field", { name: "description", class: "text-wrap" }),
            { event: { fields: FAKE_FIELDS } },
            "event",
            "calendar",
        ),
    },
    activeFields: {
        name: {
            context: "{}",
            invisible: false,
            readonly: false,
            required: false,
            onChange: false,
        },
        description: {
            context: "{}",
            invisible: false,
            readonly: false,
            required: false,
            onChange: false,
        },
    },
    rangeEnd: DEFAULT_DATE.endOf("month"),
    rangeStart: DEFAULT_DATE.startOf("month"),
    records: FAKE_RECORDS,
    resModel: "event",
    scale: "month",
    scales: ["day", "week", "month", "year"],
    unusualDays: [],
    load() {},
    createFilter() {},
    createRecord() {},
    unlinkFilter() {},
    unlinkRecord() {},
    updateFilter() {},
    updateRecord() {},
};

// DOM Utils
//------------------------------------------------------------------------------

/**
 * @param {HTMLElement} element
 */
function instantScrollTo(element) {
    // Guard so a missing element (selector mismatch in a v7 migration
    // pocket we haven't covered yet) surfaces a clear test error from
    // the caller, rather than ``Cannot read properties of null``.
    element?.scrollIntoView({ behavior: "instant", block: "center" });
}

/**
 * @param {string} date
 * @returns {HTMLElement}
 */
export function findAllDaySlot(date) {
    // v7 dropped the ``.fc-daygrid-body`` wrapper; the all-day strip is
    // just a ``[data-date=...]`` cell with no unique container. Exclude the
    // column-header cell (the only other match in day/week views).
    return queryFirst(`.fc-day[data-date="${date}"]:not(.fc-col-header-cell)`);
}

/**
 * @param {string} date
 * @returns {HTMLElement}
 */
export function findDateCell(date) {
    // Our ``dayHeaderClassNames`` injects ``.fc-day`` on column headers
    // too (so compound selectors like ``.fc-col-header-cell.fc-day``
    // keep working).  Exclude headers here so callers get the body cell.
    return queryFirst(`.fc-day[data-date="${date}"]:not(.fc-col-header-cell)`);
}

/**
 * @param {number} eventId
 * @returns {HTMLElement}
 */
export function findEvent(eventId) {
    return queryFirst(`.o_event[data-event-id="${eventId}"]`);
}

/**
 * @param {string} date
 * @returns {HTMLElement}
 */
export function findDateColumn(date) {
    return queryFirst(`.fc-col-header-cell.fc-day[data-date="${date}"]`);
}

/**
 * @param {string} time
 * @returns {HTMLElement}
 */
export function findTimeRow(time) {
    // v7 splits the v6 ``.fc-timegrid-slot`` into label + lane cells.
    // The clickable drop target is the lane.
    return queryFirst(`.fc-timegrid-slot-lane[data-time="${time}"]:eq(0)`);
}

/**
 * @param {string} sectionName
 * @returns {HTMLElement}
 */
export function findFilterPanelSection(sectionName) {
    return queryFirst(`.o_calendar_filter[data-name="${sectionName}"]`);
}

/**
 * @param {string} sectionName
 * @param {string} filterValue
 * @returns {HTMLElement}
 */
export function findFilterPanelFilter(sectionName, filterValue) {
    const root = findFilterPanelSection(sectionName);
    return queryFirst(`.o_calendar_filter_item[data-value="${filterValue}"]`, { root });
}

/**
 * @param {string} sectionName
 * @returns {HTMLElement}
 */
export function findFilterPanelSectionFilter(sectionName) {
    const root = findFilterPanelSection(sectionName);
    return queryFirst(`.o_calendar_filter_items_checkall`, { root });
}

/**
 * @param {string} date
 * @returns {Promise<void>}
 */
export async function pickDate(date) {
    const day = date.split("-")[2];
    const iDay = parseInt(day, 10) - 1;
    await click(
        `.o_datetime_picker .o_date_item_cell:not(.o_out_of_range):eq(${iDay})`,
    );
    await animationFrame();
}

/**
 * @param {string} date
 * @returns {Promise<void>}
 */
export async function clickAllDaySlot(date) {
    const slot = findAllDaySlot(date);

    instantScrollTo(slot);

    await click(slot);
    await animationFrame();
}

/**
 * @param {string} date
 * @returns {Promise<void>}
 */
export async function clickDate(date) {
    const cell = findDateCell(date);

    instantScrollTo(cell);

    await click(cell);
    await advanceTime(500);
}

/**
 * @param {number} eventId
 * @returns {Promise<void>}
 */
export async function clickEvent(eventId) {
    const eventEl = findEvent(eventId);

    instantScrollTo(eventEl);

    await click(eventEl);
    await advanceTime(500); // wait for the popover to open (debounced)
}

export function expandCalendarView() {
    let tmpElement = queryFirst(".fc");
    do {
        tmpElement = tmpElement.parentElement;
        tmpElement.classList.add("h-100");
    } while (!tmpElement.classList.contains("o_view_controller"));
}

/**
 * @param {string} startDateTime
 * @param {string} endDateTime
 * @returns {Promise<void>}
 */
export async function selectTimeRange(startDateTime, endDateTime) {
    const [startDate, startTime] = startDateTime.split(" ");
    const [endDate, endTime] = endDateTime.split(" ");

    // Try to display both rows on the screen before drag'n'drop.
    const startHour = Number(startTime.slice(0, 2));
    const endHour = Number(endTime.slice(0, 2));
    const midHour = Math.floor((startHour + endHour) / 2);
    const midTime = `${String(midHour).padStart(2, "0")}:00:00`;

    instantScrollTo(
        queryFirst(`.fc-timegrid-slot-lane[data-time="${midTime}"]:eq(0)`, {
            visible: false,
        }),
    );

    // FC v7 renders ``.fc-timegrid-slot-lane`` elements as visual
    // BACKGROUND rows OUTSIDE the interactive ``TimeGridCols`` subtree.
    // Mousedown on a slot lane reaches only FC's document-level
    // ``PointerDragging`` (unselect tracking) — never the component-level
    // ``DateSelecting`` handler, so ``select``/``createRecord`` never fire.
    //
    // The real interactive element per date is the ``TimeGridCol`` with
    // ``role='gridcell'`` and ``data-date`` (``fullcalendar.esm.js:12137``).
    // Week/day view has three per date — header (columnheader), all-day
    // strip (gridcell + .fc-daygrid-day), time-grid body (gridcell only).
    // Filter to the time-grid body by excluding the all-day class.
    //
    // Y position still comes from the slot lane's rect, kept non-zero by
    // the ``computeSlatHeight`` fork-patch's ``slotMinHeight``.
    const startCol = queryFirst(
        `[data-date="${startDate}"][role="gridcell"]:not(.fc-daygrid-day)`,
    );
    const endCol = queryFirst(
        `[data-date="${endDate}"][role="gridcell"]:not(.fc-daygrid-day)`,
    );
    const startLane = queryFirst(
        `.fc-timegrid-slot-lane[data-time="${startTime}"]:eq(0)`,
    );
    const endLane = queryFirst(`.fc-timegrid-slot-lane[data-time="${endTime}"]:eq(0)`);

    const startColRect = queryRect(startCol);
    const endColRect = queryRect(endCol);
    const startLaneRect = queryRect(startLane);
    const endLaneRect = queryRect(endLane);

    const optionStart = {
        relative: true,
        position: {
            x: startColRect.width / 2,
            y: startLaneRect.top - startColRect.top + 1,
        },
    };

    await hover(startCol, optionStart);
    await animationFrame();
    const { drop } = await drag(startCol, optionStart);
    await animationFrame();
    await drop(endCol, {
        relative: true,
        position: {
            x: endColRect.width / 2,
            y: endLaneRect.top - endColRect.top - 1,
        },
    });

    await animationFrame();
}

/**
 * Tap a single time-grid slot via its interactive column.
 *
 * FC v7 renders ``.fc-timegrid-slot-lane`` elements as non-interactive visual
 * background rows outside the ``TimeGridCols`` subtree -- a pointer event on a
 * lane never reaches FC's ``dateClick`` handler. The interactive element per
 * date is the ``TimeGridCol`` (``role='gridcell'`` + ``data-date``, excluding
 * the all-day ``.fc-daygrid-day`` cell); click it at the slot's vertical offset
 * (derived from the lane's rect, as ``selectTimeRange`` does).
 *
 * @param {string} dateTime - e.g. "2016-12-12 08:30:00"
 * @returns {Promise<void>}
 */
export async function clickTimeSlot(dateTime) {
    const [date, time] = dateTime.split(" ");
    const col = queryFirst(
        `[data-date="${date}"][role="gridcell"]:not(.fc-daygrid-day)`,
    );
    const lane = queryFirst(`.fc-timegrid-slot-lane[data-time="${time}"]:eq(0)`);
    instantScrollTo(lane);
    const colRect = queryRect(col);
    const laneRect = queryRect(lane);
    await click(col, {
        relative: true,
        position: { x: colRect.width / 2, y: laneRect.top - colRect.top + 1 },
    });
    await animationFrame();
}

/**
 * @param {string} startDate
 * @param {string} endDate
 * @returns {Promise<void>}
 */
export async function selectDateRange(startDate, endDate) {
    const startCell = findDateCell(startDate);
    const endCell = findDateCell(endDate);

    instantScrollTo(startCell);

    await hover(startCell);
    await animationFrame();

    const { moveTo, drop } = await drag(startCell);
    await animationFrame();

    await moveTo(endCell);
    await animationFrame();

    await drop();
    await animationFrame();
}

/**
 * @param {string} startDate
 * @param {string} endDate
 * @returns {Promise<void>}
 */
export async function selectAllDayRange(startDate, endDate) {
    const start = findAllDaySlot(startDate);
    const end = findAllDaySlot(endDate);

    instantScrollTo(start);

    await hover(start);
    await animationFrame();

    const { drop } = await drag(start);
    await animationFrame();

    await drop(end);
    await animationFrame();
}
export async function closeCwPopOver() {
    if (getMockEnv().isSmall) {
        await contains(`.oi-arrow-left`).click();
    } else {
        await contains(`.o_cw_popover_close`).click();
    }
}
/**
 * @param {number} eventId
 * @param {string} date
 * @param {{ disableDrop: boolean }} [options]
 * @returns {Promise<void>}
 */
export async function moveEventToDate(eventId, date, options) {
    const eventEl = findEvent(eventId);
    const cell = findDateCell(date);

    instantScrollTo(eventEl);

    await hover(eventEl);
    await animationFrame();

    const { drop, moveTo } = await drag(eventEl);
    await animationFrame();

    await moveTo(cell);
    await animationFrame();

    if (!options?.disableDrop) {
        await drop();
    }

    await animationFrame();
    await animationFrame();
}

/**
 * @param {number} eventId
 * @param {string} dateTime
 * @returns {Promise<void>}
 */
export async function moveEventToTime(eventId, dateTime) {
    const eventEl = findEvent(eventId);
    const [date, time] = dateTime.split(" ");

    instantScrollTo(eventEl);

    const row = findTimeRow(time);
    const rowRect = queryRect(row);

    const column = findDateColumn(date);
    const columnRect = queryRect(column);

    const { drop, moveTo } = await drag(eventEl, {
        position: { y: 1 },
        relative: true,
    });

    if (getMockEnv().isSmall) {
        await advanceTime(500);
    }

    await animationFrame();

    await moveTo(row, {
        position: {
            y: rowRect.y + 1,
            x: columnRect.x + columnRect.width / 2,
        },
    });
    await animationFrame();

    await drop();
    await advanceFrame(5);
}

export async function selectHourOnPicker(selectedValue) {
    await click(".o_time_picker_input:eq(0)");
    await animationFrame();
    await edit(selectedValue, { confirm: "enter" });
    await animationFrame();
}

/**
 * @param {number} eventId
 * @param {string} date
 * @returns {Promise<void>}
 */
export async function moveEventToAllDaySlot(eventId, date) {
    const eventEl = findEvent(eventId);
    const slot = findAllDaySlot(date);

    instantScrollTo(eventEl);

    const columnRect = queryRect(eventEl);
    const slotRect = queryRect(slot);

    const { drop, moveTo } = await drag(eventEl, {
        position: { y: 1 },
        relative: true,
    });

    if (getMockEnv().isSmall) {
        await advanceTime(500);
    }

    await animationFrame();

    await moveTo(slot, {
        position: {
            x: columnRect.x + columnRect.width / 2,
            y: slotRect.y,
        },
    });
    await animationFrame();

    await drop();
    await advanceFrame(5);
}

/**
 * @param {number} eventId
 * @param {string} dateTime
 * @returns {Promise<void>}
 */
export async function resizeEventToTime(eventId, dateTime) {
    // FC v7 only attaches ``fc-event-resizer-end`` to the segment whose
    // ``isEnd && eventUi.durationEditable`` are both true (see FC's
    // ``isEndResizable``). Mirror ``resizeEventToDate``'s defensive pattern:
    // query all segments, take the last, and throw a diagnostic naming the
    // FC fields to check instead of a bare null dereference.
    const allSegments = queryAll(`.o_event[data-event-id="${eventId}"]`);
    const eventEl = allSegments[allSegments.length - 1] || findEvent(eventId);

    instantScrollTo(eventEl);

    await hover(`.fc-event-main:first`, { root: eventEl });
    await animationFrame();

    const resizer = queryFirst(`.fc-event-resizer-end`, { root: eventEl });
    if (!resizer) {
        throw new Error(
            "resizeEventToTime: .fc-event-resizer-end not found inside the last " +
                `segment of event ${eventId} (${allSegments.length} segments total). ` +
                "Check 'editable' / 'isEnd' / 'durationEditable' on the FC event.",
        );
    }
    Object.assign(resizer.style, {
        display: "block",
        height: "1px",
        bottom: "0",
    });

    const [date, time] = dateTime.split(" ");

    const row = findTimeRow(time);

    const column = findDateColumn(date);
    const columnRect = queryRect(column);

    await (
        await drag(resizer)
    ).drop(row, {
        position: { x: columnRect.x, y: -1 },
        relative: true,
    });
    await advanceTime(500);
}

/**
 * @param {number} eventId
 * @param {string} date
 * @returns {Promise<void>}
 */
export async function resizeEventToDate(eventId, date) {
    // FC v7 splits multi-day all-day events into one DOM node per day row
    // (same ``data-event-id``). The ``isEnd`` flag — and hence the
    // ``fc-event-resizer-end`` class (``fullcalendar.esm.js:8945``:
    // ``isEndResizable = !disableResizing && props.isEnd &&
    // eventUi.durationEditable``) — only sits on the LAST segment.
    // ``findEvent`` returned the FIRST, so the resizer was null, throwing
    // on ``style`` — seen in the "Resizing Pill of Multiple Days(Allday)"
    // and "create event and resize to next day (24h) on week mode" tests.
    // Query all segments and take the last for the resizer search.
    const allSegments = queryAll(`.o_event[data-event-id="${eventId}"]`);
    const eventEl = allSegments[allSegments.length - 1] || findEvent(eventId);
    const slot = findAllDaySlot(date);

    instantScrollTo(eventEl);

    await hover(".fc-event-main", { root: eventEl });
    await animationFrame();

    // Show the resizer
    const resizer = queryFirst(".fc-event-resizer-end", { root: eventEl });
    if (!resizer) {
        throw new Error(
            "resizeEventToDate: .fc-event-resizer-end not found inside the last " +
                `segment of event ${eventId} (${allSegments.length} segments total). ` +
                "Check 'editable' / 'isEnd' / 'durationEditable' on the FC event.",
        );
    }
    Object.assign(resizer.style, { display: "block", height: "1px", bottom: "0" });

    instantScrollTo(slot);

    const rowRect = queryRect(resizer);

    // Find the date cell and calculate the positions for dragging
    const dateCell = findDateCell(date);
    const columnRect = queryRect(dateCell);

    // Perform the drag-and-drop operation
    await hover(resizer, {
        position: { x: 0 },
        relative: true,
    });
    await animationFrame();

    const { drop } = await drag(resizer);
    await animationFrame();

    await drop(dateCell, {
        position: { y: rowRect.y - columnRect.y },
        relative: true,
    });
    await advanceTime(500);
}

/**
 * @param {"day" | "week" | "month" | "year"} scale
 * @returns {Promise<void>}
 */
export async function changeScale(scale) {
    await contains(`.o_view_scale_selector .scale_button_selection`).click();
    await contains(`.o-dropdown--menu .o_scale_button_${scale}`).click();
}

export async function displayCalendarPanel() {
    if (getMockEnv().isSmall) {
        await contains(".o_calendar_container .o_other_calendar_panel").click();
    }
}

export async function hideCalendarPanel() {
    if (getMockEnv().isSmall) {
        await contains(".o_calendar_container .o_other_calendar_panel").click();
    }
}

/**
 * @param {"prev" | "next"} direction
 * @returns {Promise<void>}
 */
export async function navigate(direction) {
    if (getMockEnv().isSmall) {
        if (direction === "next") {
            await swipeLeft(".o_calendar_widget");
        } else {
            await swipeRight(".o_calendar_widget");
        }
        await advanceFrame(16);
    } else {
        await contains(
            `.o_calendar_navigation_buttons .o_calendar_button_${direction}`,
        ).click();
    }
}

/**
 * @param {string} sectionName
 * @param {string} filterValue
 * @returns {Promise<void>}
 */
export async function toggleFilter(sectionName, filterValue) {
    const otherCalendarPanel = queryFirst(".o_other_calendar_panel");
    if (otherCalendarPanel) {
        click(otherCalendarPanel);
        await animationFrame();
    }
    const root = findFilterPanelFilter(sectionName, filterValue);
    const input = queryFirst(`input`, { root });

    instantScrollTo(input);

    await click(input);
    await animationFrame();

    if (otherCalendarPanel) {
        await click(otherCalendarPanel);
        await animationFrame();
    }
    await advanceTime(CalendarModel.DEBOUNCED_LOAD_DELAY);
    await animationFrame();
}

/**
 * @param {string} sectionName
 * @returns {Promise<void>}
 */
export async function toggleSectionFilter(sectionName) {
    const otherCalendarPanel = queryFirst(".o_other_calendar_panel");
    if (otherCalendarPanel) {
        await click(otherCalendarPanel);
        await animationFrame();
    }
    const root = findFilterPanelSectionFilter(sectionName);
    const input = queryFirst(`input`, { root });

    instantScrollTo(input);

    await click(input);
    await animationFrame();

    if (otherCalendarPanel) {
        await click(otherCalendarPanel);
        await animationFrame();
    }
    await advanceTime(CalendarModel.DEBOUNCED_LOAD_DELAY);
    await animationFrame();
}

/**
 * @param {string} sectionName
 * @param {string} filterValue
 * @returns {Promise<void>}
 */
export async function removeFilter(sectionName, filterValue) {
    const root = findFilterPanelFilter(sectionName, filterValue);
    const button = queryFirst(`.o_remove`, { root });

    instantScrollTo(button);

    await click(button);
    await advanceTime(CalendarModel.DEBOUNCED_LOAD_DELAY);
    await animationFrame();
}
