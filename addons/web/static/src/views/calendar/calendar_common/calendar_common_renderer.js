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
 * Format a Luxon DateTime as a bare, offset-less ISO string suitable for
 * FullCalendar's ``initialDate`` option.
 *
 * FC v7 parses an offset-bearing ISO into an absolute moment then re-derives
 * the day in its declared ``timeZone`` — which, in a fixed-offset/marker zone
 * (or in tests), can cross a UTC boundary and land on the previous day when the
 * source is local midnight. Emitting wall-clock time with no offset tells FC to
 * interpret the value in its configured zone, which is what callers mean.
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
        // Pass a GETTER, not the snapshot.  v7 needs fresh ``initialView``
        // / ``initialDate`` / ``editable`` / ... on every ``onPatched``;
        // capturing the object once at setup time strands the hook on
        // stale values when the OWL scale/date props change.
        this.fc = useFullCalendar("fullCalendar", () => this.options);
        this.clickTimeoutId = null;
        // The single-click timer (250ms, see onEventClick) would otherwise fire
        // onClick on a destroyed renderer when the user navigates/changes scale
        // within the window — this renderer remounts on scale/date change.
        onWillUnmount(() => browser.clearTimeout(this.clickTimeoutId));
        this.popover = useCalendarPopover(
            /** @type {any} */ (this.constructor).components.Popover,
        );
        this.timeFormat = is24HourFormat() ? "HH:mm" : "hh:mm a";
        useBus(this.props.model.bus, ModelEvent.SCROLL_TO_CURRENT_HOUR, () => {
            // Subtract 2h so the current hour lands near the top of the
            // visible area, leaving prior context above.  Clamp to 0
            // because FC v7's ``createDuration`` rejects negative time
            // strings and ``scrollToTime`` becomes a silent no-op
            // otherwise — observed when the local hour is 0 or 1.
            const targetHour = Math.max(0, DateTime.local().hour - 2);
            this.fc.api.scrollToTime(`${targetHour}:00:00`);
        });

        useSquareSelection({
            cellIsSelectable: /** @type {any} */ (this.constructor).cellIsSelectable,
        });
    }

    get options() {
        return {
            // v7 minifies the root and view class names into per-build
            // hashes — the legacy ``fc`` / ``fc-timeGridDay-view``
            // / ``fc-dayGridMonth-view`` class hooks are gone.  Tests
            // (and downstream CSS/JS selectors throughout the fork) still
            // target those names, so we re-inject them via v7's
            // ``class`` (root) and ``viewClass`` (per-view) class-name
            // generators.  ``viewClass`` receives a renderProps object
            // with ``view.type`` so we mirror v6's ``fc-<viewName>-view``
            // pattern exactly.
            class: "fc",
            viewClass: ({ view }) =>
                view && view.type ? `fc-view fc-${view.type}-view` : "fc-view",
            // v7 dropped all the human-readable ``fc-*`` class hooks
            // (``fc-day``, ``fc-col-header-cell``, ``fc-event-main``…)
            // in favour of per-build hashed names.  Re-inject the
            // ones the fork's CSS and tests depend on through v7's
            // per-element class-name-generator options
            // (``dayCellClass``, ``dayHeaderClass``, …).  Each generator
            // is called per render and its return value joined onto
            // whatever v7 produces, so layering is non-destructive.
            //
            // ``dayCellClass`` accepts a function (cell-info → string|string[]
            // returned by FC's ``generateClassName`` helper) so we can
            // recover the v6 state-suffix hooks (``fc-day-other`` on cells
            // outside the displayed month, ``fc-day-disabled`` on disabled
            // cells, etc.).  Tests and CSS selectors throughout the fork
            // depend on these.
            dayCellClass: this.dayCellClass,
            dayCellInnerClass: "fc-daygrid-day-frame",
            dayCellTopClass: "fc-daygrid-day-top",
            dayCellTopInnerClass: "fc-daygrid-day-number",
            dayHeaderClass: dayHeaderClassNames,
            // ``eventClass`` is layered onto every event element.  The
            // body-event-specific subclasses (``fc-daygrid-event``,
            // ``fc-timegrid-event``) used to differentiate dayGrid vs
            // timeGrid events in v6; v7 hashed them.  Tests select by
            // both the generic ``.fc-event`` (still emitted via our
            // generator) and the grid-specific subclasses (re-injected
            // through ``rowEventClass`` / ``columnEventClass``).
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
            // v7 still renders a popover for "+N more" overflow; the
            // tests close it via ``.o_cw_popover_close`` which is the
            // Odoo close button injected by the popover content.  v7
            // exposes its own ``fc-popover-close`` hook too.
            popoverClass: "fc-popover",
            popoverCloseClass: "fc-popover-close",
            // v7's timegrid axis cell for the week label is otherwise
            // hashed.  ``weekNumberHeaderClass`` lands on the cell and
            // ``weekNumberHeaderInnerClass`` on the inner span; tests
            // target ``.fc-week-number`` for the text content.  This
            // is the only v7 element that gets the ``Week N`` label in
            // timegrid views, so it does NOT clash with the daygrid
            // inline week-number (which renders only in month view).
            weekNumberHeaderClass: "fc-week-number",
            inlineWeekNumberClass: "fc-daygrid-week-number",
            // v6 daygrid-body / row hooks.  ``tableBodyClass`` is
            // applied to every daygrid-style body wrapper (main month
            // body AND the all-day strip in timegrid views).  Tests
            // distinguish contexts via the parent view class —
            // ``.fc-timeGridWeek-view .fc-daygrid-body`` picks the
            // all-day strip; ``.fc-dayGridMonth-view .fc-daygrid-body``
            // picks the main body.  Compound-class tests that don't
            // scope to a view (``.fc-daygrid-body .fc-event``) need
            // updating to use ``.fc-daygrid-event`` (our
            // ``rowEventClass`` injection) to target the all-day strip
            // events specifically.
            tableBodyClass: "fc-daygrid-body",
            dayRowClass: "fc-daygrid-row",
            // v6 timegrid hooks.  Both the slot lane (the half-hour
            // cells in the body) AND the slot header (the time-of-day
            // label in the axis) had ``fc-timegrid-slot`` in v6; tests
            // disambiguate via ``-lane`` vs ``-label`` suffixes.  The
            // label is what carries the visible text (``"8am"``,
            // ``"11pm"``…); re-inject the v6 class so tests asserting on
            // the label text by data-time keep finding the right node.
            // v7 exposes the major/minor distinction via the className
            // generator's ``renderProps`` (``isMinor`` is true for the
            // unlabeled half-hour lanes). A static string would drop the v6
            // ``fc-timegrid-slot-minor`` marker that tests target to tap/select
            // a sub-hour slot, so generate it per lane.
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
            // v7 routes ``display: "background"`` events through a
            // separate ``backgroundEventDidMount`` callback rather than
            // ``eventDidMount`` — without this, ``data-event-id`` and
            // the ``o_event*`` modifier classes never land on the
            // background event elements (used for all-day events that
            // span timegrid columns).
            backgroundEventDidMount: this.onEventDidMount,
            eventContent: this.onEventContent,
            eventResizableFromStart: true,
            eventResize: this.onEventResize,
            eventResizeStart: this.onEventResizeStart,
            events: (_, successCb) => successCb(this.mapRecordsToEvents()),
            firstDay: this.props.model.firstDayOfWeek,
            headerToolbar: false,
            height: "100%",
            // ``slotMinHeight`` is treated as the per-slot floor by FC v7's
            // ``computeSlatHeight``: ``Math.max(slatInnerHeight + 1,
            // explicitSlatMinHeight)``.  Setting 22px matches the natural
            // slot height in this fork's UX (label line-height + padding)
            // and pairs with the fork-local patch in
            // ``lib/fullcalendar/fullcalendar.esm.js`` that uses this
            // value as a fall-back when label measurement is delayed (HOOT
            // tests with deferred layout, ResizeObserver pending, etc.).
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
            weekNumberCalculation: (date) => getLocalYearAndWeek(date).week,
            weekNumbers: true,
            dayHeaderContent: this.getHeaderHtml,
            eventDisplay: "block", // Restore old render in daygrid view for single-day timed events
            eventTimeFormat: is24HourFormat() ? HOUR_FORMATS[24] : HOUR_FORMATS[12],
            viewDidMount: this.viewDidMount,
            fixedWeekCount: false,
            // FC v7's ``StandardEvent.render`` only mounts the after-class
            // <div> (which carries the ``fc-event-resizer-end`` re-injected
            // by the fork patch at ``fullcalendar.esm.js`` line 9020)
            // when ``afterClassName || afterContent`` is truthy.  Without
            // a non-empty class generator for column/row events, the div
            // is omitted entirely and the resize handle disappears even
            // when ``isEndResizable`` is true.  Provide a stable, content-
            // neutral class so the slot exists for every event; the
            // resize-end / resize-start variants of ``isStartResizable`` /
            // ``isEndResizable`` then add the cursor + resizer classes
            // onto it.  Same rationale on the start side (line 9015) for
            // ``eventResizableFromStart: true`` to take visible effect.
            columnEventAfterClass: "o_event_after",
            rowEventAfterClass: "o_event_after",
            columnEventBeforeClass: "o_event_before",
            rowEventBeforeClass: "o_event_before",
            // FC v7 stopped attaching the v6 ``fc-highlight`` class to
            // the date-range selection overlay (it now uses internal hashed
            // classes via ``classNames.fill``).  Tests and CSS still target
            // ``.fc-highlight`` for select-range visibility, so re-inject
            // via the public ``highlightClass`` option.  The class is
            // applied wherever FC renders a ``fillType === 'highlight'``
            // segment — including ``selectMirror`` overlays.
            highlightClass: "fc-highlight",
        };
    }

    get customOptions() {
        return {
            weekNumbersWithinDays: !this.env.isSmall,
        };
    }

    viewDidMount({ el, view, options }) {
        // v7 dropped ``view.calendar.currentData.options`` — the same
        // calendar options now arrive directly as the ``options`` field
        // of the didMount payload (see ``fullcalendar.esm.js:5358``
        // for the actual ``didMount({ ...renderProps, el })`` call).
        // ``view`` itself only exposes ``{ type, getCurrentData, dateEnv }``
        // in v7, so the old ``view.calendar`` reach-through is gone.
        if (!options) {
            return; // v6-shape fallback or unexpected payload
        }
        // FC v7's didMount payload echoes only a subset of options (the
        // toolbars), not weekNumbers/weekTextShort. Read the week-number config
        // from the renderer's own FullCalendar options rather than the partial
        // didMount payload, which would otherwise leave showWeek undefined and
        // skip the mobile week-number column entirely.
        const showWeek = this.options.weekNumbers;
        const weekText = options.weekTextShort ?? this.options.weekText ?? "";
        const weekColumn = !this.customOptions.weekNumbersWithinDays;
        if (showWeek && weekColumn) {
            makeWeekColumn(/** @type {any} */ ({ el, weekText }));
        }
        // v6 exposed ``fc-scroller`` (and ``fc-scroller-liquid-y``) on
        // every Scroller wrapper. v7 hashes those class names —
        // ``internalScroller`` for the wrapper and ``liquid`` for the
        // growing vertical scroller — and regenerates the hashes on every
        // build, so they're resolved at runtime via ``fcInternalClassName``
        // rather than hard-coded. Tests, fork CSS in
        // ``calendar_renderer.scss``, and downstream addons still target the
        // v6 names; re-inject them in-place so the stable name lives next to
        // the hashed one without overriding FC's internal styling.
        //
        // Two scrollers per timegrid view: the day-name column header
        // (horizontal, no overflow growth, not ``liquid``) and the time
        // body (vertical, growing content, ``liquid``). Only the vertical
        // scroller is auto-scrolled to ``scrollTime`` by ``applyTimeScroll``
        // and is therefore the meaningful test anchor for
        // ``[data-time="06:00:00"]`` alignment assertions.
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
        this.openPopover(info.el, this.props.model.records[info.event.id]);
        this.highlightEvent(info.event, "o_cw_custom_highlight");
    }
    onDateClick(info) {
        if (info.jsEvent.defaultPrevented) {
            return;
        }
        this.props.createRecord(this.fcEventToRecord(info));
    }
    getDayCellClassNames(info) {
        const date = DateTime.fromJSDate(info.date).toISODate();
        if (this.props.model.unusualDays.includes(date)) {
            return ["o_calendar_disabled"];
        }
        return [];
    }
    /**
     * v7 ``dayCellClass`` generator — combines base v6 day-cell hooks
     * (``fc-day``, grid-specific suffixes, state suffixes from cell
     * render-props) with model-driven classes like ``o_calendar_disabled``
     * for unusual days.  Declarative classes survive re-renders, unlike
     * classes added imperatively in ``dayCellDidMount`` which v7 may wipe
     * on partial updates.
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
        this.props.editRecord(this.props.model.records[info.event.id]);
    }
    onEventClick(info) {
        if (this.clickTimeoutId) {
            this.onDblClick(info);
            browser.clearTimeout(this.clickTimeoutId);
            this.clickTimeoutId = null;
        } else {
            this.clickTimeoutId = browser.setTimeout(() => {
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
            // This is needed in order to give the possibility to change the event template.
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
            // All-day records normalize ``end`` to ``end.startOf("day")``, so a
            // single-day all-day event's ``end`` is midnight of that same day —
            // comparing against it would grey the event out for its whole last
            // day. Treat an all-day event as past only once its final day is
            // fully over (i.e. at the start of the following day).
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
        // v7's renderProps shape varies between cell contexts (timegrid
        // vs daygrid vs multimonth); ``info.el`` is the cell element
        // when present.  Guard so a single bad payload doesn't take
        // down the whole mount.
        if (classes.length && info.el) {
            info.el.classList.add(...classes);
        }
        this.injectMobileWeekNumber(info);
    }
    /**
     * Render the mobile month-view week-number cell.
     *
     * FullCalendar v7 suppresses its inline week number on "micro" cells
     * (``cellWidth <= 60px``, always the case on a phone-width month grid), so
     * the dedicated week column the mobile layout expects never appears. This
     * hook fires for every day cell on every render -- unlike ``viewDidMount``,
     * which runs once and whose imperative edits FullCalendar discards on the
     * next body re-render -- so injecting here keeps the column stable. The
     * companion ``.o-fc-week-header`` is added by ``makeWeekColumn``.
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
        weekCell.textContent = String(getLocalYearAndWeek(info.date).week);
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
        // Compare the whole calendar day, not just the day-of-month: getDate()
        // returns 1–31, so a timed selection spanning the same day number in a
        // different month (e.g. Mar 3 → Apr 3) was wrongly treated as same-day.
        if (event.allDay) {
            return true;
        }
        // A timed selection ending exactly at midnight (e.g. 23:00→24:00) has
        // its end roll over to 00:00 of the next day; without this the last
        // slot of a day could never be drag-selected. Treat an end at exactly
        // 00:00 as belonging to the previous day.
        let end = event.end;
        if (
            end.getHours() === 0 &&
            end.getMinutes() === 0 &&
            end.getSeconds() === 0 &&
            end.getMilliseconds() === 0
        ) {
            end = new Date(end.getTime() - 1);
        }
        return event.start.toDateString() === end.toDateString();
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
        // FullCalendar v7 emits two different Date conventions to the
        // ``select`` / ``eventDrop`` / ``eventResize`` callbacks depending
        // on the ``timeZone`` option:
        //   - IANA / named zone (e.g. ``"Africa/Algiers"``): real-epoch
        //     Date — getTime() is the wall-clock instant.  ``fromJSDate``
        //     reads correctly: the local zone applied by Luxon matches
        //     FC's interpretation.
        //   - ``"local"`` (returned by ``getFullCalendarTimeZone()`` for
        //     ``FixedOffsetZone`` defaults like ``mockTimeZone(N)``): a
        //     **marker** Date — its UTC components encode the visible
        //     local-clock components, not the real wall-clock instant.
        //     A click at local 06:00 with ``mockTimeZone(2)`` arrives as
        //     ``new Date("2016-12-13T06:00:00Z")`` (the UTC encoding of
        //     06:00 local), *not* ``"2016-12-13T04:00:00Z"`` (the real
        //     UTC instant).  ``fromJSDate`` mis-adds the offset twice and
        //     lands the record at 08:00 local / 06:00 UTC instead of
        //     06:00 local / 04:00 UTC.
        //
        // Detect the ``"local"`` case by re-querying the timezone string
        // and rebuild the DateTime from UTC components in the local zone
        // so serializers produce the user-visible clock time.  See
        // ``fullcalendar.esm.js:1767-1789`` (``timestampToMarker`` /
        // ``toDate``) for the FC-side conversion this mirrors.
        const isMarkerMode = getFullCalendarTimeZone() === "local";
        const Lux = DateTime;
        const fromFcDate = (d) => {
            if (!isMarkerMode) {
                return Lux.fromJSDate(d);
            }
            // Marker dates from FC v7's drag/drop can pick up
            // sub-minute drift when the test harness's ``Date.now()``
            // is mocked but continues to advance during the gesture —
            // a moved event arrives with ``HH:mm:01.123Z`` instead of
            // ``HH:mm:00.000Z``. Snap to the calendar's
            // ``snapDuration`` (15 minutes) by truncating seconds and
            // milliseconds; sub-minute precision is meaningless for a
            // drag-drop on a 15-minute grid anyway.
            return Lux.fromObject({
                year: d.getUTCFullYear(),
                month: d.getUTCMonth() + 1,
                day: d.getUTCDate(),
                hour: d.getUTCHours(),
                minute: d.getUTCMinutes(),
            });
        };
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
        // so use UTC instead of local tz when converting to DateTime
        const options = scale === "month" ? { zone: "UTC" } : {};
        const { weekdayShort, weekdayLong, day } = DateTime.fromJSDate(date, options);
        return {
            weekdayShort,
            weekdayLong,
            day,
            scale,
        };
    }
}
