// @ts-check
/** @odoo-module native */

/** @module @web/views/calendar/calendar_year/calendar_year_renderer */

import { Component, useEffect, useExternalListener, useRef } from "@odoo/owl";
import { getLocalYearAndWeek } from "@web/core/l10n/dates";
import { localization } from "@web/core/l10n/localization";
import { DateTime, Info, Interval, Settings } from "@web/core/l10n/luxon";
import { useReactiveModel } from "@web/model/model";
import { formatFcInitialDate } from "@web/views/calendar/calendar_common/calendar_common_renderer";
import { makeWeekColumn } from "@web/views/calendar/calendar_common/calendar_common_week_column";
import { convertRecordToEvent, getColor } from "@web/views/calendar/calendar_utils";
import { CalendarYearPopover } from "@web/views/calendar/calendar_year/calendar_year_popover";
import { useCalendarPopover } from "@web/views/calendar/hooks/calendar_popover_hook";
import {
    dayCellClassNames,
    dayHeaderClassNames,
    fcInternalClassName,
    fromFcDate,
    getFullCalendarTimeZone,
    useFullCalendar,
} from "@web/views/calendar/hooks/full_calendar_hook";

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

    /** @type {{}} */
    fcs;
    /** @type {ReturnType<typeof useCalendarPopover>} */
    popover;
    /** @type {import("@odoo/owl").Ref} */
    rootRef;

    setup() {
        // Subscribe to the model rather than reading it off the raw prop, so a
        // `notify()` re-renders this component on its own instead of relying on
        // the controller's blanket deep render.
        this.model = useReactiveModel(this.props.model);
        this.months = Info.months();
        this.fcs = {};
        for (const month of this.months) {
            this.fcs[month] = useFullCalendar(`fullCalendar-${month}`, () =>
                this.getOptionsForMonth(month),
            );
        }
        this.popover = useCalendarPopover(
            /** @type {any} */ (this.constructor).components.Popover,
        );
        this.rootRef = useRef("root");

        useEffect(
            () => this.updateSize(),
            () => [this.rootRef.el],
        );

        useExternalListener(window, "resize", () => this.onWindowResize());
    }

    get options() {
        return {
            class: "fc",
            viewClass: ({ view }) =>
                view && view.type ? `fc-view fc-${view.type}-view` : "fc-view",
            dayCellClass: this.dayCellClass,
            dayCellInnerClass: "fc-daygrid-day-frame",
            dayCellTopClass: "fc-daygrid-day-top",
            dayCellTopInnerClass: "fc-daygrid-day-number",
            dayHeaderClass: dayHeaderClassNames,
            backgroundEventClass: "fc-bg-event",
            toolbarClass: "fc-toolbar",
            toolbarSectionClass: "fc-toolbar-chunk",
            toolbarTitleClass: "fc-toolbar-title",
            dayHeaderFormat: { weekday: "narrow" },
            dateClick: this.onDateClick,
            dayCellDidMount: this.onDayCellDidMount,
            initialDate: formatFcInitialDate(this.model.date),
            initialView: "dayGridMonth",
            direction: localization.direction,
            droppable: true,
            editable: this.model.canEdit,
            dayMaxEventRows: this.model.eventLimit,
            eventDidMount: this.onEventDidMount,
            backgroundEventDidMount: this.onEventDidMount,
            eventResizableFromStart: true,
            events: (_, successCb) => successCb(this.mapRecordsToEvents()),
            firstDay: this.model.firstDayOfWeek,
            headerToolbar: { start: false, center: "title", end: false },
            height: "auto",
            locale: Settings.defaultLocale,
            longPressDelay: 500,
            navLinks: false,
            nowIndicator: true,
            select: this.onSelect,
            selectMinDistance: 5,
            selectMirror: true,
            selectable: this.model.canCreate,
            showNonCurrentDates: false,
            timeZone: getFullCalendarTimeZone(),
            titleFormat: { month: "long", year: "numeric" },
            unselectAuto: false,
            weekNumberCalculation: (date) => getLocalYearAndWeek(fromFcDate(date)).week,
            weekNumbers: false,
            weekNumberFormat: { week: "numeric" },
            eventContent: this.onEventContent,
            viewDidMount: this.viewDidMount,
            weekends: this.props.isWeekendVisible,
            fixedWeekCount: false,
            highlightClass: "fc-highlight",
        };
    }

    get customOptions() {
        return {
            weekNumbersWithinDays: true,
        };
    }

    viewDidMount({ el, view, options }) {
        if (!options) {
            return;
        }
        const showWeek = this.options.weekNumbers;
        const weekText = options.weekTextShort ?? this.options.weekText ?? "";
        const weekColumn = !this.customOptions.weekNumbersWithinDays;
        if (showWeek && weekColumn) {
            makeWeekColumn(/** @type {any} */ ({ el, weekText }));
        }
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
        return Object.values(this.model.records).map((r) =>
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
        return formatFcInitialDate(
            this.model.date.set({ month: this.months.indexOf(month) + 1 }),
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
            model: this.model,
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
            this.model.load({
                date: DateTime.fromISO(info.dateStr),
                scale: "day",
            });
            return;
        }

        const date = DateTime.fromISO(info.dateStr);
        const records = Object.values(this.model.records).filter((r) =>
            Interval.fromDateTimes(r.start.startOf("day"), r.end.endOf("day")).contains(
                date,
            ),
        );

        this.popover.close();
        if (records.length) {
            const target = info.dayEl;
            this.openPopover(target, date, records);
        } else if (this.model.canCreate) {
            this.props.createRecord({
                start: DateTime.fromISO(info.dateStr),
                isAllDay: true,
            });
        }
    }
    dayCellClass(info) {
        const base = dayCellClassNames(info);
        const extras = this.getDayCellClassNames(info);
        return extras.length ? `${base} ${extras.join(" ")}` : base;
    }
    getDayCellClassNames(info) {
        const date = fromFcDate(info.date).toISODate();
        if (this.model.unusualDays.includes(date)) {
            return ["o_calendar_disabled"];
        }
        return [];
    }
    eventClassNames({ event }) {
        const classesToAdd = [];
        classesToAdd.push("o_event");
        const record = this.model.records[event.id];
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
        const record = this.model.records[event.id];
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
        if (info.event.display?.includes("background")) {
            return null;
        }
    }
}
