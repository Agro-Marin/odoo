// @ts-check
/** @odoo-module native */

/** @module @web/views/calendar/calendar_common/calendar_common_renderer - FullCalendar renderer for day/week/month scales */

import { Component, onWillUnmount } from "@odoo/owl";
import { browser } from "@web/core/browser/browser";
import { ModelEvent } from "@web/core/events";
import { getLocalYearAndWeek } from "@web/core/l10n/dates";
import { localization } from "@web/core/l10n/localization";
import { DateTime, Settings } from "@web/core/l10n/luxon";
import { is24HourFormat } from "@web/core/l10n/time";
import { useBus } from "@web/core/utils/hooks";
import { renderToFragment, renderToString } from "@web/core/utils/render";
import { CalendarCommonPopover } from "@web/views/calendar/calendar_common/calendar_common_popover";
import { makeWeekColumn } from "@web/views/calendar/calendar_common/calendar_common_week_column";
import { convertRecordToEvent, getColor } from "@web/views/calendar/calendar_utils";
import { useCalendarPopover } from "@web/views/calendar/hooks/calendar_popover_hook";
import {
    dayCellClassNames,
    dayHeaderClassNames,
    fcInternalClassName,
    fromFcDate,
    getFullCalendarTimeZone,
    useFullCalendar,
} from "@web/views/calendar/hooks/full_calendar_hook";
import { useSquareSelection } from "@web/views/calendar/hooks/square_selection_hook";

const SCALE_TO_FC_VIEW = {
    day: "timeGridDay",
    week: "timeGridWeek",
    month: "dayGridMonth",
};
// v7 uses Intl.DateTimeFormat option objects natively; v6's luxon3 plugin
// (now removed) interpreted luxon token strings via FC's cmdFormatter hook.
const SCALE_TO_HEADER_FORMAT = {
    day: { weekday: "long", day: "numeric", month: "long", year: "numeric" },
    week: { weekday: "short", day: "numeric" },
    month: { weekday: "long" },
};
const SHORT_SCALE_TO_HEADER_FORMAT = {
    ...SCALE_TO_HEADER_FORMAT,
    day: { day: "numeric", month: "numeric", year: "numeric" },
    month: { weekday: "short" },
};
/**
 * Format a Luxon DateTime as a bare, offset-less ISO string for FullCalendar's
 * ``initialDate`` option.
 *
 * FC v7 re-derives the day from an offset-bearing ISO in its declared
 * ``timeZone``, which can cross a UTC boundary and land on the previous day
 * for local midnight in a fixed-offset/marker zone. Wall-clock time with no
 * offset tells FC to interpret it in its configured zone as callers intend.
 *
 * @param {import("@web/core/l10n/luxon").DateTime} dt
 * @returns {string}
 */
export function formatFcInitialDate(dt) {
    return dt.toFormat("yyyy-MM-dd'T'HH:mm:ss");
}

const HOUR_FORMATS = {
    12: {
        hour: "numeric",
        minute: "2-digit",
        omitZeroMinute: true,
        meridiem: "short",
    },
    24: {
        hour: "numeric",
        minute: "2-digit",
        hour12: false,
    },
};

/**
 * Renderer for day, week, and month calendar scales.
 *
 * Wraps a FullCalendar instance, handles event rendering with custom templates,
 * popover management, drag/drop/resize interactions, click vs double-click
 * detection, and square cell selection for multi-create in month view.
 */
export class CalendarCommonRenderer extends Component {
    static components = {
        Popover: CalendarCommonPopover,
    };
    static template = "web.CalendarCommonRenderer";
    static eventTemplate = "web.CalendarCommonRenderer.event";
    static headerTemplate = "web.CalendarCommonRendererHeader";
    static props = {
        model: Object,
        isWeekendVisible: { type: Boolean, optional: true },
        createRecord: Function,
        editRecord: Function,
        deleteRecord: Function,
        setDate: { type: Function, optional: true },
        callbackRecorder: Object,
        onSquareSelection: Function,
        cleanSquareSelection: Function,
    };

    setup() {
        // Pass a GETTER, not the snapshot — v7 needs fresh initialView/
        // initialDate/editable on every onPatched, and a snapshot captured
        // once at setup would go stale when scale/date props change.
        this.fc = useFullCalendar("fullCalendar", () => this.options);
        this.clickTimeoutId = null;
        // The single-click timer (250ms, see onEventClick) would otherwise
        // fire on a destroyed renderer when scale/date changes remount it
        // within the window.
        onWillUnmount(() => browser.clearTimeout(this.clickTimeoutId));
        this.popover = useCalendarPopover(
            /** @type {any} */ (this.constructor).components.Popover,
        );
        this.timeFormat = is24HourFormat() ? "HH:mm" : "hh:mm a";
        useBus(this.props.model.bus, ModelEvent.SCROLL_TO_CURRENT_HOUR, () => {
            // Subtract 2h so the current hour lands near the top with prior
            // context visible; clamp to 0 since FC v7's createDuration
            // rejects negative time strings, making scrollToTime a silent
            // no-op otherwise (seen when the local hour is 0 or 1).
            const targetHour = Math.max(0, DateTime.local().hour - 2);
            this.fc.api.scrollToTime(`${targetHour}:00:00`);
        });

        useSquareSelection({
            cellIsSelectable: /** @type {any} */ (this.constructor).cellIsSelectable,
        });
    }

    get options() {
        return {
            // v7 hashes root/view class names; tests and fork CSS still
            // target the legacy fc / fc-<viewName>-view hooks, so re-inject
            // them via v7's class/viewClass generators (mirroring v6's
            // fc-<viewName>-view pattern).
            class: "fc",
            viewClass: ({ view }) =>
                view && view.type ? `fc-view fc-${view.type}-view` : "fc-view",
            // v7 hashes former fc-* class hooks (fc-day, fc-col-header-cell,
            // fc-event-main…); re-inject the ones fork CSS/tests depend on
            // via v7's per-element class-name generators, layered
            // non-destructively onto v7's own output.
            // dayCellClass also recovers v6 state suffixes (fc-day-other,
            // fc-day-disabled) that tests/CSS select on.
            dayCellClass: this.dayCellClass,
            dayCellInnerClass: "fc-daygrid-day-frame",
            dayCellTopClass: "fc-daygrid-day-top",
            dayCellTopInnerClass: "fc-daygrid-day-number",
            dayHeaderClass: dayHeaderClassNames,
            // eventClass layers onto every event element. v6's
            // fc-daygrid-event/fc-timegrid-event subclasses are hashed in
            // v7; re-inject them via rowEventClass/columnEventClass so
            // tests can select both the generic and grid-specific classes.
            eventClass: "fc-event",
            eventInnerClass: "fc-event-main",
            rowEventClass: "fc-daygrid-event",
            columnEventClass: "fc-timegrid-event",
            backgroundEventClass: "fc-bg-event",
            backgroundEventInnerClass: "fc-event-main",
            eventTimeClass: "fc-time fc-event-time",
            columnMoreLinkClass: "fc-more-link",
            rowMoreLinkClass: "fc-more-link",
            headerToolbarClass: "fc-toolbar",
            toolbarClass: "fc-toolbar",
            toolbarSectionClass: "fc-toolbar-chunk",
            toolbarTitleClass: "fc-toolbar-title",
            // v7 still renders a "+N more" popover; tests close it via
            // .o_cw_popover_close (Odoo's injected button); v7 also exposes
            // its own fc-popover-close hook.
            popoverClass: "fc-popover",
            popoverCloseClass: "fc-popover-close",
            // v7 hashes the timegrid axis week-label cell; re-inject via
            // weekNumberHeaderClass (cell) / weekNumberHeaderInnerClass
            // (inner span). Tests target .fc-week-number; this doesn't
            // clash with the daygrid inline week-number (month view only).
            weekNumberHeaderClass: "fc-week-number",
            inlineWeekNumberClass: "fc-daygrid-week-number",
            // v6 daygrid-body/row hooks. tableBodyClass applies to every
            // daygrid-style body wrapper (month body AND timegrid all-day
            // strip); tests disambiguate via the parent view class
            // (.fc-timeGridWeek-view vs .fc-dayGridMonth-view .fc-daygrid-body).
            tableBodyClass: "fc-daygrid-body",
            dayRowClass: "fc-daygrid-row",
            // v6's fc-timegrid-slot covered both the slot lane (half-hour
            // body cells) and slot header (axis time label); tests
            // disambiguate via -lane/-label suffixes. v7 exposes the
            // major/minor distinction via renderProps.isMinor, so generate
            // the class per lane to keep the fc-timegrid-slot-minor marker
            // tests use to target sub-hour slots.
            slotLaneClass: (renderProps) =>
                renderProps.isMinor
                    ? "fc-timegrid-slot fc-timegrid-slot-lane fc-timegrid-slot-minor"
                    : "fc-timegrid-slot fc-timegrid-slot-lane",
            slotHeaderClass: "fc-timegrid-slot fc-timegrid-slot-label",
            slotHeaderInnerClass: "fc-timegrid-slot-label-cushion",
            allDaySlot: true,
            allDayText: "",
            dayHeaderFormat: this.env.isSmall
                ? SHORT_SCALE_TO_HEADER_FORMAT[this.props.model.scale]
                : SCALE_TO_HEADER_FORMAT[this.props.model.scale],
            // we must handle clicks differently in multicreate mode:
            // fc is blocked by safePrevent in onPointerDown (draggable_hook_builder.js)
            dateClick: this.props.model.hasMultiCreate ? () => {} : this.onDateClick,
            dayCellDidMount: this.onDayCellDidMount,
            // Pass the date as a bare local-style ISO (no offset); see
            // formatFcInitialDate for why the offset must be stripped.
            initialDate: formatFcInitialDate(this.props.model.date),
            initialView: SCALE_TO_FC_VIEW[this.props.model.scale],
            direction: localization.direction,
            droppable: true,
            editable: this.props.model.canEdit,
            eventClick: this.onEventClick,
            eventDragStart: this.onEventDragStart,
            eventDrop: this.onEventDrop,
            dayMaxEventRows: this.props.model.eventLimit,
            moreLinkClick: this.onEventLimitClick,
            eventMouseEnter: this.onEventMouseEnter,
            eventMouseLeave: this.onEventMouseLeave,
            eventDidMount: this.onEventDidMount,
            // v7 routes display:"background" events through
            // backgroundEventDidMount rather than eventDidMount; without
            // this, data-event-id and o_event* classes never land on
            // background events (all-day events spanning timegrid columns).
            backgroundEventDidMount: this.onEventDidMount,
            eventContent: this.onEventContent,
            eventResizableFromStart: true,
            eventResize: this.onEventResize,
            eventResizeStart: this.onEventResizeStart,
            events: (_, successCb) => successCb(this.mapRecordsToEvents()),
            firstDay: this.props.model.firstDayOfWeek,
            headerToolbar: false,
            height: "100%",
            // slotMinHeight is FC v7's computeSlatHeight floor
            // (Math.max(slatInnerHeight + 1, explicitSlatMinHeight)). 22px
            // matches this fork's natural slot height and pairs with the
            // fork-local fullcalendar.esm.js patch that falls back to it
            // when label measurement is delayed (deferred layout in tests).
            slotMinHeight: 22,
            locale: Settings.defaultLocale,
            longPressDelay: 500,
            navLinks: false,
            nowIndicator: true,
            nowIndicatorDotClass: "o_calendar_time_indicator_now",
            select: this.onSelect,
            selectAllow: this.isSelectionAllowed,
            selectMinDistance: 5, // needed to not trigger select when click
            selectMirror: true,
            selectable: !this.props.model.hasMultiCreate && this.props.model.canCreate,
            showNonCurrentDates: this.props.model.monthOverflow,
            slotHeaderFormat: is24HourFormat() ? HOUR_FORMATS[24] : HOUR_FORMATS[12],
            snapDuration: { minutes: 15 },
            timeZone: getFullCalendarTimeZone(),
            unselectAuto: false,
            weekNumberFormat: {
                week:
                    this.props.model.scale === "month" || this.env.isSmall
                        ? "numeric"
                        : "long",
            },
            weekends: this.props.isWeekendVisible,
            weekNumberCalculation: (date) => getLocalYearAndWeek(fromFcDate(date)).week,
            weekNumbers: true,
            dayHeaderContent: this.getHeaderHtml,
            eventDisplay: "block", // Restore old render in daygrid view for single-day timed events
            eventTimeFormat: is24HourFormat() ? HOUR_FORMATS[24] : HOUR_FORMATS[12],
            viewDidMount: this.viewDidMount,
            fixedWeekCount: false,
            // FC v7's StandardEvent.render only mounts the after-class div
            // (carries the fork-patched fc-event-resizer-end,
            // fullcalendar.esm.js) when afterClassName||afterContent is
            // truthy, so without a non-empty generator the resize handle
            // vanishes even when isEndResizable is true. Same rationale on
            // the start side (line 9015) for eventResizableFromStart.
            columnEventAfterClass: "o_event_after",
            rowEventAfterClass: "o_event_after",
            columnEventBeforeClass: "o_event_before",
            rowEventBeforeClass: "o_event_before",
            // FC v7 dropped the v6 fc-highlight class on the date-range
            // selection overlay (now uses internal hashed classNames.fill
            // classes); re-inject via highlightClass so tests/CSS targeting
            // .fc-highlight keep working, including selectMirror overlays.
            highlightClass: "fc-highlight",
        };
    }

    get customOptions() {
        return {
            weekNumbersWithinDays: !this.env.isSmall,
        };
    }

    viewDidMount({ el, view, options }) {
        // v7 dropped view.calendar.currentData.options; the same options
        // now arrive directly as the options field of the didMount payload
        // (fullcalendar.esm.js). view itself is just { type,
        // getCurrentData, dateEnv } in v7.
        if (!options) {
            return; // v6-shape fallback or unexpected payload
        }
        // The didMount payload only echoes a subset of options (toolbars),
        // not weekNumbers/weekTextShort, so read those from this.options
        // instead — otherwise showWeek is undefined and the mobile
        // week-number column is skipped entirely.
        const showWeek = this.options.weekNumbers;
        const weekText = options.weekTextShort ?? this.options.weekText ?? "";
        const weekColumn = !this.customOptions.weekNumbersWithinDays;
        if (showWeek && weekColumn) {
            makeWeekColumn(/** @type {any} */ ({ el, weekText }));
        }
        // v6 exposed fc-scroller/fc-scroller-liquid-y on every Scroller
        // wrapper; v7 hashes those (internalScroller/liquid, regenerated
        // per build), resolved at runtime via fcInternalClassName. Tests
        // and fork CSS/downstream addons still target the v6 names, so
        // re-inject them alongside the hashed ones without overriding FC's
        // internal styling.
        //
        // Two scrollers per timegrid view: the day-name header (horizontal,
        // not liquid) and the time body (vertical, liquid) — only the
        // latter is auto-scrolled by applyTimeScroll and is the meaningful
        // anchor for [data-time="06:00:00"] alignment assertions.
        const scrollerClass = fcInternalClassName("internalScroller");
        const liquidClass = fcInternalClassName("liquid");
        for (const scrollerEl of el.querySelectorAll(`.${scrollerClass}`)) {
            scrollerEl.classList.add("fc-scroller");
            if (scrollerEl.classList.contains(liquidClass)) {
                scrollerEl.classList.add("fc-scroller-liquid-y");
            }
        }
    }

    getStartTime(record) {
        return record.start.toFormat(this.timeFormat);
    }

    getEndTime(record) {
        return record.end.toFormat(this.timeFormat);
    }

    computeEventSelector(event) {
        return `[data-event-id="${event.id}"]`;
    }
    highlightEvent(event, className) {
        for (const el of this.fc.api.el.querySelectorAll(
            this.computeEventSelector(event),
        )) {
            el.classList.add(className);
        }
    }
    unhighlightEvent(event, className) {
        for (const el of this.fc.api.el.querySelectorAll(
            this.computeEventSelector(event),
        )) {
            el.classList.remove(className);
        }
    }
    /** @returns {Object[]} model records converted to FullCalendar event objects */
    mapRecordsToEvents() {
        return Object.values(this.props.model.records).map((r) =>
            this.convertRecordToEvent(r),
        );
    }
    convertRecordToEvent(record) {
        return convertRecordToEvent(record);
    }
    getPopoverProps(record) {
        return {
            record,
            model: this.props.model,
            createRecord: this.props.createRecord,
            deleteRecord: this.props.deleteRecord,
            editRecord: this.props.editRecord,
        };
    }
    openPopover(target, record) {
        const color = getColor(record.colorIndex);
        this.popover.open(
            target,
            this.getPopoverProps(record),
            `o_cw_popover card o_calendar_color_${typeof color === "number" ? color : 0}`,
        );
    }

    onClick(info) {
        // The single-click path runs on a 250ms timer; a load landing in that
        // window (filter toggle, another session's change) can drop the
        // record, and openPopover → getColor(record.colorIndex) would throw on
        // undefined. Bail if the record is gone.
        const record = this.props.model.records[info.event.id];
        if (!record) {
            return;
        }
        this.openPopover(info.el, record);
        this.highlightEvent(info.event, "o_cw_custom_highlight");
    }
    onDateClick(info) {
        if (info.jsEvent.defaultPrevented) {
            return;
        }
        this.props.createRecord(this.fcEventToRecord(info));
    }
    getDayCellClassNames(info) {
        const date = fromFcDate(info.date).toISODate();
        if (this.props.model.unusualDays.includes(date)) {
            return ["o_calendar_disabled"];
        }
        return [];
    }
    /**
     * v7 dayCellClass generator — combines base v6 day-cell hooks with
     * model-driven classes like o_calendar_disabled. Declarative classes
     * survive re-renders, unlike imperative dayCellDidMount edits which v7
     * may wipe on partial updates.
     *
     * :param info: cell render-props supplied by FullCalendar
     * :return: space-joined day-cell class names
     * :rtype: string
     */
    dayCellClass(info) {
        const base = dayCellClassNames(info);
        const extras = this.getDayCellClassNames(info);
        return extras.length ? `${base} ${extras.join(" ")}` : base;
    }
    onDblClick(info) {
        const record = this.props.model.records[info.event.id];
        if (!record) {
            // Same race as onClick: a reload within the double-click window can
            // drop the record; editRecord(undefined) would throw on record.id.
            return;
        }
        this.props.editRecord(record);
    }
    onEventClick(info) {
        if (this.clickTimeoutId) {
            this.onDblClick(info);
            browser.clearTimeout(this.clickTimeoutId);
            this.clickTimeoutId = null;
        } else {
            this.clickTimeoutId = browser.setTimeout(() => {
                // An FC re-render inside the 250ms window (event refetch,
                // filter toggle) can detach info.el; re-resolve the anchor so
                // the popover doesn't position against a dead node. Only when
                // actually detached — the event may have several segments
                // (e.g. one in the "+N more" popover) and a blind
                // querySelector would swap the clicked one for the first.
                if (!info.el.isConnected) {
                    info.el =
                        this.fc.api.el.querySelector(
                            this.computeEventSelector(info.event),
                        ) || info.el;
                }
                this.onClick(info);
                this.clickTimeoutId = null;
            }, 250);
        }
    }
    onEventContent(arg) {
        const { event } = arg;
        if (event.start && event.end) {
            const dateFmt = (date) =>
                DateTime.fromJSDate(date).toFormat(this.timeFormat);
            arg.timeText = `${dateFmt(event.start)} - ${dateFmt(event.end)}`;
        }
        const record = this.props.model.records[event.id];
        if (record) {
            // Allows subclasses to override the event template.
            const fragment = renderToFragment(
                /** @type {any} */ (this.constructor).eventTemplate,
                {
                    ...record,
                    startTime: this.getStartTime(record),
                    endTime: this.getEndTime(record),
                },
            );
            return { domNodes: fragment.children };
        }
        return true;
    }
    eventClassNames({ el, event }) {
        const classesToAdd = [];
        classesToAdd.push("o_event");
        const record = this.props.model.records[event.id];

        if (record) {
            const color = getColor(record.colorIndex);
            if (typeof color === "number") {
                classesToAdd.push(`o_calendar_color_${color}`);
            } else if (typeof color !== "string") {
                classesToAdd.push("o_calendar_color_0");
            }

            if (record.isHatched) {
                classesToAdd.push("o_event_hatched");
            }
            if (record.isStriked) {
                classesToAdd.push("o_event_striked");
            }
            if (record.duration <= 0.25) {
                classesToAdd.push("o_event_oneliner");
            }
            // All-day end is normalized to startOf("day"), so a single-day
            // event's end is midnight that same day — comparing directly
            // would grey it out all last day. Treat it as past only once its
            // final day is fully over (start of the following day).
            const pastThreshold = record.isAllDay
                ? record.end.plus({ days: 1 })
                : record.end;
            if (DateTime.now() >= pastThreshold) {
                classesToAdd.push("o_past_event");
            }

            if (!record.isAllDay && !record.isTimeHidden && record.isMonth) {
                classesToAdd.push("o_event_dot");
            } else if (record.isAllDay) {
                classesToAdd.push("o_event_allday");
            }
        }
        return classesToAdd;
    }
    onDayCellDidMount(info) {
        const classes = this.getDayCellClassNames(info);
        // v7's renderProps shape varies by cell context (timegrid/daygrid/
        // multimonth); guard so a single bad payload doesn't crash the mount.
        if (classes.length && info.el) {
            info.el.classList.add(...classes);
        }
        this.injectMobileWeekNumber(info);
    }
    /**
     * Render the mobile month-view week-number cell.
     *
     * FC v7 suppresses its inline week number on "micro" cells (cellWidth
     * <= 60px, always true on a phone-width month grid). This hook fires per
     * day cell on every render — unlike viewDidMount (runs once; FC discards
     * its imperative edits on the next body re-render) — so injecting here
     * keeps the column stable. Companion .o-fc-week-header is added by
     * makeWeekColumn.
     *
     * @param {Object} info - FullCalendar dayCellDidMount payload ({ el, date })
     */
    injectMobileWeekNumber(info) {
        if (
            !this.env.isSmall ||
            this.customOptions.weekNumbersWithinDays ||
            !this.options.weekNumbers ||
            !info.el?.parentElement ||
            !info.date
        ) {
            return;
        }
        const row = info.el.parentElement;
        // Only act when the row's first day cell mounts, and never duplicate.
        if (
            row.querySelector(".fc-daygrid-day") !== info.el ||
            row.querySelector(".o-fc-week")
        ) {
            return;
        }
        const weekCell = document.createElement("div");
        weekCell.classList.add("o-fc-week");
        weekCell.setAttribute("role", "gridcell");
        weekCell.textContent = String(getLocalYearAndWeek(fromFcDate(info.date)).week);
        row.prepend(weekCell);
    }
    onEventDidMount(info) {
        const { el, event } = info;
        // v7 dropped function-form eventClass; apply dynamic classes here so
        // module overrides of eventClassNames continue to work via super chain.
        const classes = this.eventClassNames(info);
        if (classes.length) {
            el.classList.add(...classes);
        }
        el.dataset.eventId = event.id;
        const record = this.props.model.records[event.id];

        if (record) {
            if (record.isMonth) {
                el.querySelector(".fc-event-main").classList.add(
                    "d-flex",
                    "gap-1",
                    "text-truncate",
                );
            }
            const color = getColor(record.colorIndex);
            if (typeof color === "string") {
                el.style.backgroundColor = color;
            }

            if (!el.classList.contains("fc-bg")) {
                const bg = document.createElement("div");
                bg.classList.add("fc-bg");
                el.appendChild(bg);
            }
        }
    }
    async onSelect(info) {
        info.jsEvent.preventDefault();
        this.popover.close();
        await this.props.createRecord(this.fcEventToRecord(info));
        this.fc.api.unselect();
    }
    isSelectionAllowed(event) {
        if (event.allDay) {
            return true;
        }
        // Every FC date consumer must go through fromFcDate (see
        // full_calendar_hook): raw getHours()/toDateString() evaluate in the
        // BROWSER timezone, so when the user's profile tz differs from the
        // browser tz a grid-visible same-day selection could be blocked (and
        // a cross-midnight one allowed). Convert to the marker-aware Luxon
        // DateTime first, then compare calendar days there.
        const start = fromFcDate(event.start);
        let end = fromFcDate(event.end);
        // A timed selection ending exactly at midnight (e.g. 23:00→24:00) rolls
        // its end over to 00:00 of the next day; treat that as the previous
        // day so the last slot of a day stays drag-selectable.
        if (
            end.hour === 0 &&
            end.minute === 0 &&
            end.second === 0 &&
            end.millisecond === 0
        ) {
            end = end.minus({ milliseconds: 1 });
        }
        return start.hasSame(end, "day");
    }
    onEventDrop(info) {
        this.fc.api.unselect();
        this.props.model.updateRecord(this.fcEventToRecord(info.event), {
            moved: true,
        });
    }
    onEventResize(info) {
        this.fc.api.unselect();
        this.props.model.updateRecord(this.fcEventToRecord(info.event));
    }
    /**
     * Convert a FullCalendar event object back into a calendar record.
     *
     * @param {Object} event - FullCalendar event with id, allDay, date/start/end
     * @returns {Object} record with luxon DateTime start/end and optional id
     */
    fcEventToRecord(event) {
        const { id, allDay, date, start, end } = event;
        // fromFcDate handles FC v7's two Date conventions (real-epoch for
        // IANA zones, marker Dates in "local" mode) — see its docstring in
        // full_calendar_hook.js.
        const res = {
            start: fromFcDate(date || start),
            isAllDay: allDay,
        };
        if (end) {
            res.end = fromFcDate(end);
            // FullCalendar reports all-day ranges with an EXCLUSIVE end in
            // every scale — day view's all-day strip included — so the -1 day
            // correction applies to all three timeGrid/dayGrid scales.
            if (["day", "week", "month"].includes(this.props.model.scale) && allDay) {
                res.end = res.end.minus({ days: 1 });
            }
        }
        if (id) {
            const existingRecord = this.props.model.records[id];
            if (this.props.model.scale === "month") {
                res.start = res.start?.set({
                    hour: existingRecord.start.hour,
                    minute: existingRecord.start.minute,
                });
                if (existingRecord.end) {
                    res.end = res.end?.set({
                        hour: existingRecord.end.hour,
                        minute: existingRecord.end.minute,
                    });
                }
            }
            res.id = existingRecord.id;
        }
        return res;
    }
    onEventMouseEnter(info) {
        this.highlightEvent(info.event, "o_cw_custom_highlight");
    }
    onEventMouseLeave(info) {
        if (!info.event.id) {
            return;
        }
        this.unhighlightEvent(info.event, "o_cw_custom_highlight");
    }
    onEventDragStart(info) {
        this.popover.close();
        this.props.cleanSquareSelection();
        info.el.classList.add(info.view.type);
        // FC v7 renders the drag mirror without firing ``eventDidMount``, so it
        // never receives the fork's event classes (``o_event`` et al.) the way
        // a normal event does. ``eventDragStart`` does fire on the mirror, so
        // apply them here to keep the dragged event consistent with rendered
        // events for CSS and ``.o_event`` selectors.
        info.el.classList.add(...this.eventClassNames(info));
        this.fc.api.unselect();
        this.highlightEvent(info.event, "o_cw_custom_highlight");
    }
    onEventResizeStart(info) {
        this.props.cleanSquareSelection();
        this.fc.api.unselect();
        this.highlightEvent(info.event, "o_cw_custom_highlight");
    }
    onEventLimitClick() {
        this.fc.api.unselect();
        return "popover";
    }

    getHeaderHtml({ date }) {
        return {
            html: renderToString(
                /** @type {any} */ (this.constructor).headerTemplate,
                this.headerTemplateProps(date),
            ),
        };
    }

    headerTemplateProps(date) {
        const scale = this.props.model.scale;
        // when rendering months, FullCalendar uses a date w/out tz
        // so use UTC instead of local tz when converting to DateTime;
        // day/week headers carry zone-dependent dates — marker-aware.
        const dt =
            scale === "month"
                ? DateTime.fromJSDate(date, { zone: "UTC" })
                : fromFcDate(date);
        const { weekdayShort, weekdayLong, day } = dt;
        return {
            weekdayShort,
            weekdayLong,
            day,
            scale,
        };
    }
}
