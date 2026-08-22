// @ts-check
/** @odoo-module native */

import { useEffect, useExternalListener, useRef } from "@odoo/owl";
import { getLocalYearAndWeek } from "@web/core/l10n/dates";
import { localization } from "@web/core/l10n/localization";
import { DateTime, Info, Interval, Settings } from "@web/core/l10n/luxon";
import { useReactiveModel } from "@web/model/model";
import { formatFcInitialDate } from "@web/views/calendar/calendar_common/calendar_common_renderer";
import { CalendarRendererBase } from "@web/views/calendar/calendar_renderer_base";
import { convertRecordToEvent } from "@web/views/calendar/calendar_utils";
import { CalendarYearPopover } from "@web/views/calendar/calendar_year/calendar_year_popover";
import { useCalendarPopover } from "@web/views/calendar/hooks/calendar_popover_hook";
import {
    fcViewClassOptions,
    fromFcDate,
    getFullCalendarTimeZone,
    useFullCalendar,
} from "@web/views/calendar/hooks/full_calendar_hook";

export class CalendarYearRenderer extends CalendarRendererBase {
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
            ...fcViewClassOptions(this.dayCellClass),
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
