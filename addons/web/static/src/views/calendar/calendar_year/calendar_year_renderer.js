// @ts-check
/** @odoo-module native */

/** @module @web/views/calendar/calendar_year/calendar_year_renderer - Year-scale renderer displaying 12 mini month grids with background events */

import { Component, useEffect, useExternalListener, useRef } from "@odoo/owl";
import { getLocalYearAndWeek } from "@web/core/l10n/dates";
import { localization } from "@web/core/l10n/localization";
import { DateTime, Info, Interval, Settings } from "@web/core/l10n/luxon";
import { formatFcInitialDate } from "@web/views/calendar/calendar_common/calendar_common_renderer";
import { makeWeekColumn } from "@web/views/calendar/calendar_common/calendar_common_week_column";
import { convertRecordToEvent, getColor } from "@web/views/calendar/calendar_utils";
import { CalendarYearPopover } from "@web/views/calendar/calendar_year/calendar_year_popover";
import { useCalendarPopover } from "@web/views/calendar/hooks/calendar_popover_hook";
import {
    dayCellClassNames,
    dayHeaderClassNames,
    fcInternalClassName,
    getFullCalendarTimeZone,
    useFullCalendar,
} from "@web/views/calendar/hooks/full_calendar_hook";

/** Year-scale calendar renderer displaying 12 mini month grids with background events. */
export class CalendarYearRenderer extends Component {
    static components = {
        Popover: CalendarYearPopover,
    };
    static template = "web.CalendarYearRenderer";
    static props = {
        model: Object,
        createRecord: Function,
        editRecord: Function,
        deleteRecord: Function,
        isWeekendVisible: { type: Boolean, optional: true },
    };

    setup() {
        this.months = Info.months();
        this.fcs = {};
        for (const month of this.months) {
            // Pass a GETTER so v7 sees fresh options on every patch: the options
            // carry model-dependent callbacks, so capturing them once would strand
            // calendars on first-mount values when navigating between years.
            this.fcs[month] = useFullCalendar(`fullCalendar-${month}`, () =>
                this.getOptionsForMonth(month),
            );
        }
        this.popover = useCalendarPopover(
            /** @type {any} */ (this.constructor).components.Popover,
        );
        this.rootRef = useRef("root");

        useEffect(() => {
            this.updateSize();
        });

        // v7 dropped v6's ``windowResize`` option (ResizeObserver only); re-create
        // the per-instance fan-out by listening on ``window`` directly and invoking
        // once per mini calendar. Tests count the expected 12 invocations.
        useExternalListener(window, "resize", () => {
            for (let i = 0; i < this.months.length; i++) {
                this.onWindowResize();
            }
        });
    }

    get options() {
        return {
            // v7 hashed the v6 ``fc-day-*`` state classes; re-inject the v6 names
            // tests and CSS still target (see ``dayCellClassNames``).
            class: "fc",
            viewClass: ({ view }) =>
                view && view.type ? `fc-view fc-${view.type}-view` : "fc-view",
            dayCellClass: this.dayCellClass,
            dayCellInnerClass: "fc-daygrid-day-frame",
            dayCellTopClass: "fc-daygrid-day-top",
            dayCellTopInnerClass: "fc-daygrid-day-number",
            dayHeaderClass: dayHeaderClassNames,
            // Year view uses ``display: "background"`` for events.
            backgroundEventClass: "fc-bg-event",
            // v7 toolbar splits into ``toolbarSectionClass`` elements; re-inject
            // v6's ``fc-toolbar-chunk`` so tests targeting mini-calendar titles work.
            toolbarClass: "fc-toolbar",
            toolbarSectionClass: "fc-toolbar-chunk",
            toolbarTitleClass: "fc-toolbar-title",
            dayHeaderFormat: { weekday: "narrow" },
            dateClick: this.onDateClick,
            dayCellDidMount: this.onDayCellDidMount,
            // Strip the offset (see formatFcInitialDate): an offset-bearing ISO
            // makes FC re-derive the day in its zone and land on the previous
            // day in fixed-offset/marker zones, mis-anchoring the mini months.
            initialDate: formatFcInitialDate(this.props.model.date),
            initialView: "dayGridMonth",
            direction: localization.direction,
            droppable: true,
            editable: this.props.model.canEdit,
            dayMaxEventRows: this.props.model.eventLimit,
            eventDidMount: this.onEventDidMount,
            // Year view events use ``display: "background"`` (see
            // ``convertRecordToEvent``), routed by v7 through
            // ``backgroundEventDidMount`` instead of ``eventDidMount``. Without this,
            // ``data-event-id``/``o_event*`` classes never land and id-based test
            // selectors find 0 elements.
            backgroundEventDidMount: this.onEventDidMount,
            eventResizableFromStart: true,
            events: (_, successCb) => successCb(this.mapRecordsToEvents()),
            firstDay: this.props.model.firstDayOfWeek,
            headerToolbar: { start: false, center: "title", end: false },
            height: "auto",
            locale: Settings.defaultLocale,
            longPressDelay: 500,
            navLinks: false,
            nowIndicator: true,
            select: this.onSelect,
            selectMinDistance: 5, // needed to not trigger select when click
            selectMirror: true,
            selectable: this.props.model.canCreate,
            showNonCurrentDates: false,
            timeZone: getFullCalendarTimeZone(),
            titleFormat: { month: "long", year: "numeric" },
            unselectAuto: false,
            weekNumberCalculation: (date) => getLocalYearAndWeek(date).week,
            weekNumbers: false,
            weekNumberFormat: { week: "numeric" },
            eventContent: this.onEventContent,
            viewDidMount: this.viewDidMount,
            weekends: this.props.isWeekendVisible,
            fixedWeekCount: false,
            // Same rationale as ``calendar_common_renderer``: re-inject v6's
            // ``fc-highlight`` class so tests/CSS targeting it work under FC v7.
            highlightClass: "fc-highlight",
        };
    }

    get customOptions() {
        return {
            weekNumbersWithinDays: true,
        };
    }

    viewDidMount({ el, view, options }) {
        // v7 dropped ``view.calendar.currentData.options``; the same options now
        // arrive as the ``options`` field of the didMount payload
        // (``fullcalendar.esm.js:5358``).
        if (!options) {
            return; // v6-shape fallback or unexpected payload
        }
        const showWeek = options.weekNumbers;
        const weekText = options.weekTextShort;
        const weekColumn = !this.customOptions.weekNumbersWithinDays;
        if (showWeek && weekColumn) {
            makeWeekColumn(/** @type {any} */ ({ el, weekText }));
        }
        // Same scroller-class re-injection as ``CalendarCommonRenderer.viewDidMount``:
        // downstream CSS still targets ``.fc-scroller`` (see calendar_renderer.scss).
        // Hashes are resolved at runtime so they survive FC library bumps.
        const scrollerClass = fcInternalClassName("internalScroller");
        const liquidClass = fcInternalClassName("liquid");
        for (const scrollerEl of el.querySelectorAll(`.${scrollerClass}`)) {
            scrollerEl.classList.add("fc-scroller");
            if (scrollerEl.classList.contains(liquidClass)) {
                scrollerEl.classList.add("fc-scroller-liquid-y");
            }
        }
    }

    mapRecordsToEvents() {
        return Object.values(this.props.model.records).map((r) =>
            this.convertRecordToEvent(r),
        );
    }
    convertRecordToEvent(record) {
        return {
            ...convertRecordToEvent(record, true),
            display: "background",
        };
    }
    getDateWithMonth(month) {
        // Strip the offset (see formatFcInitialDate): this is the per-month anchor
        // fed to FC as initialDate; an offset-bearing ISO would land on the previous
        // day in fixed-offset/marker zones, shifting the whole mini month.
        return formatFcInitialDate(
            this.props.model.date.set({ month: this.months.indexOf(month) + 1 }),
        );
    }
    getOptionsForMonth(month) {
        return {
            ...this.options,
            initialDate: this.getDateWithMonth(month),
        };
    }
    getPopoverProps(date, records) {
        return {
            date,
            records,
            model: this.props.model,
            createRecord: this.props.createRecord,
            deleteRecord: this.props.deleteRecord,
            editRecord: this.props.editRecord,
        };
    }
    openPopover(target, date, records) {
        this.popover.open(target, this.getPopoverProps(date, records), "o_cw_popover");
    }
    unselect() {
        for (const fc of Object.values(this.fcs)) {
            fc.api.unselect();
        }
    }
    updateSize() {
        const height = window.innerHeight - this.rootRef.el.getBoundingClientRect().top;
        this.rootRef.el.style.height = `${height}px`;
    }

    onDateClick(info) {
        if (this.env.isSmall) {
            this.props.model.load({
                date: DateTime.fromISO(info.dateStr),
                scale: "day",
            });
            return;
        }

        // With date value we don't want to change the time, we need the exact date
        const date = DateTime.fromISO(info.dateStr);
        const records = Object.values(this.props.model.records).filter((r) =>
            Interval.fromDateTimes(r.start.startOf("day"), r.end.endOf("day")).contains(
                date,
            ),
        );

        this.popover.close();
        if (records.length) {
            const target = info.dayEl;
            this.openPopover(target, date, records);
        } else if (this.props.model.canCreate) {
            this.props.createRecord({
                // With date value we don't want to change the time, we need the exact date
                start: DateTime.fromISO(info.dateStr),
                isAllDay: true,
            });
        }
    }
    /**
     * v7 ``dayCellClass`` generator: combines base v6 day-cell hooks with
     * ``o_calendar_disabled`` for unusual days. Declarative so classes survive
     * v7 re-renders (unlike imperative additions in ``dayCellDidMount``).
     */
    dayCellClass(info) {
        const base = dayCellClassNames(info);
        const extras = this.getDayCellClassNames(info);
        return extras.length ? `${base} ${extras.join(" ")}` : base;
    }
    getDayCellClassNames(info) {
        const date = DateTime.fromJSDate(info.date).toISODate();
        if (this.props.model.unusualDays.includes(date)) {
            return ["o_calendar_disabled"];
        }
        return [];
    }
    eventClassNames({ event }) {
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
        }
        return classesToAdd;
    }
    onDayCellDidMount(info) {
        const classes = this.getDayCellClassNames(info);
        // v7's renderProps shape varies between cell contexts; ``info.el`` may be
        // absent on some payloads, so guard against a bad payload taking down the mount.
        if (classes.length && info.el) {
            info.el.classList.add(...classes);
        }
    }
    onEventDidMount(info) {
        const { el, event } = info;
        const classes = this.eventClassNames(info);
        if (classes.length) {
            el.classList.add(...classes);
        }
        el.dataset.eventId = event.id;
        const record = this.props.model.records[event.id];
        if (record) {
            const color = getColor(record.colorIndex);
            if (typeof color === "string") {
                el.style.backgroundColor = color;
            }
        }
    }
    async onSelect(info) {
        this.popover.close();
        await this.props.createRecord({
            // With date value we don't want to change the time, we need the exact date
            start: DateTime.fromISO(info.startStr),
            end: DateTime.fromISO(info.endStr).minus({ days: 1 }),
            isAllDay: true,
        });
        this.unselect();
    }
    onWindowResize() {
        this.updateSize();
    }

    onEventContent(info) {
        // Remove the title on the background event like in FCv4
        if (info.event.display?.includes("background")) {
            return null;
        }
    }
}
