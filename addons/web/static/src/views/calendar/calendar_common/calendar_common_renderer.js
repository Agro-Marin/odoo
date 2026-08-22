// @ts-check
/** @odoo-module native */

import { onWillUnmount } from "@odoo/owl";
import { browser } from "@web/core/browser/browser";
import { ModelEvent } from "@web/core/events";
import { getLocalYearAndWeek } from "@web/core/l10n/dates";
import { localization } from "@web/core/l10n/localization";
import { DateTime, Settings } from "@web/core/l10n/luxon";
import { is24HourFormat } from "@web/core/l10n/time";
import { useBus } from "@web/core/utils/hooks";
import { renderToFragment, renderToString } from "@web/core/utils/render";
import { useReactiveModel } from "@web/model/model";
import { CalendarCommonPopover } from "@web/views/calendar/calendar_common/calendar_common_popover";
import { CalendarRendererBase } from "@web/views/calendar/calendar_renderer_base";
import { convertRecordToEvent, getColor } from "@web/views/calendar/calendar_utils";
import { useCalendarPopover } from "@web/views/calendar/hooks/calendar_popover_hook";
import {
    fcViewClassOptions,
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

export class CalendarCommonRenderer extends CalendarRendererBase {
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

    /** @type {null | number} */
    clickTimeoutId;
    /** @type {ReturnType<typeof useFullCalendar>} */
    fc;
    /** @type {ReturnType<typeof useCalendarPopover>} */
    popover;

    setup() {
        this.model = useReactiveModel(this.props.model);
        this.fc = useFullCalendar("fullCalendar", () => this.options);
        this.clickTimeoutId = null;
        this.pendingClickEventId = null;
        this.pendingClick = null;
        onWillUnmount(() => browser.clearTimeout(this.clickTimeoutId));
        this.popover = useCalendarPopover(
            /** @type {any} */ (this.constructor).components.Popover,
        );
        this.timeFormat = is24HourFormat() ? "HH:mm" : "hh:mm a";
        useBus(this.model.bus, ModelEvent.SCROLL_TO_CURRENT_HOUR, () => {
            const targetHour = Math.max(0, DateTime.local().hour - 2);
            this.fc.api.scrollToTime(`${targetHour}:00:00`);
        });

        useSquareSelection({
            cellIsSelectable: /** @type {any} */ (this.constructor).cellIsSelectable,
        });
    }

    get options() {
        return {
            ...fcViewClassOptions(this.dayCellClass),
            eventClass: "fc-event",
            eventInnerClass: "fc-event-main",
            rowEventClass: "fc-daygrid-event",
            columnEventClass: "fc-timegrid-event",
            backgroundEventInnerClass: "fc-event-main",
            eventTimeClass: "fc-time fc-event-time",
            columnMoreLinkClass: "fc-more-link",
            rowMoreLinkClass: "fc-more-link",
            headerToolbarClass: "fc-toolbar",
            toolbarClass: "fc-toolbar",
            toolbarSectionClass: "fc-toolbar-chunk",
            toolbarTitleClass: "fc-toolbar-title",
            popoverClass: "fc-popover",
            popoverCloseClass: "fc-popover-close",
            weekNumberHeaderClass: "fc-week-number",
            inlineWeekNumberClass: "fc-daygrid-week-number",
            tableBodyClass: "fc-daygrid-body",
            dayRowClass: "fc-daygrid-row",
            slotLaneClass: (renderProps) =>
                renderProps.isMinor
                    ? "fc-timegrid-slot fc-timegrid-slot-lane fc-timegrid-slot-minor"
                    : "fc-timegrid-slot fc-timegrid-slot-lane",
            slotHeaderClass: "fc-timegrid-slot fc-timegrid-slot-label",
            slotHeaderInnerClass: "fc-timegrid-slot-label-cushion",
            allDaySlot: true,
            allDayText: "",
            dayHeaderFormat: this.env.isSmall
                ? SHORT_SCALE_TO_HEADER_FORMAT[this.model.scale]
                : SCALE_TO_HEADER_FORMAT[this.model.scale],
            dateClick: this.model.hasMultiCreate ? () => {} : this.onDateClick,
            dayCellDidMount: this.onDayCellDidMount,
            initialDate: formatFcInitialDate(this.model.date),
            initialView: SCALE_TO_FC_VIEW[this.model.scale],
            direction: localization.direction,
            droppable: true,
            editable: this.model.canEdit,
            eventClick: this.onEventClick,
            eventDragStart: this.onEventDragStart,
            eventDrop: this.onEventDrop,
            dayMaxEventRows: this.model.eventLimit,
            moreLinkClick: this.onEventLimitClick,
            eventMouseEnter: this.onEventMouseEnter,
            eventMouseLeave: this.onEventMouseLeave,
            eventDidMount: this.onEventDidMount,
            backgroundEventDidMount: this.onEventDidMount,
            eventContent: this.onEventContent,
            eventResizableFromStart: true,
            eventResize: this.onEventResize,
            eventResizeStart: this.onEventResizeStart,
            events: (_, successCb) => successCb(this.mapRecordsToEvents()),
            firstDay: this.model.firstDayOfWeek,
            headerToolbar: false,
            height: "100%",
            slotMinHeight: 22,
            locale: Settings.defaultLocale,
            longPressDelay: 500,
            navLinks: false,
            nowIndicator: true,
            nowIndicatorDotClass: "o_calendar_time_indicator_now",
            select: this.onSelect,
            selectAllow: this.isSelectionAllowed,
            selectMinDistance: 5,
            selectMirror: true,
            selectable: !this.model.hasMultiCreate && this.model.canCreate,
            showNonCurrentDates: this.model.monthOverflow,
            slotHeaderFormat: is24HourFormat() ? HOUR_FORMATS[24] : HOUR_FORMATS[12],
            snapDuration: { minutes: 15 },
            timeZone: getFullCalendarTimeZone(),
            unselectAuto: false,
            weekNumberFormat: {
                week:
                    this.model.scale === "month" || this.env.isSmall
                        ? "numeric"
                        : "long",
            },
            weekends: this.props.isWeekendVisible,
            weekNumberCalculation: (date) => getLocalYearAndWeek(fromFcDate(date)).week,
            weekNumbers: true,
            dayHeaderContent: this.getHeaderHtml,
            eventDisplay: "block",
            eventTimeFormat: is24HourFormat() ? HOUR_FORMATS[24] : HOUR_FORMATS[12],
            viewDidMount: this.viewDidMount,
            fixedWeekCount: false,
            columnEventAfterClass: "o_event_after",
            rowEventAfterClass: "o_event_after",
            columnEventBeforeClass: "o_event_before",
            rowEventBeforeClass: "o_event_before",
            highlightClass: "fc-highlight",
        };
    }

    get customOptions() {
        return {
            weekNumbersWithinDays: !this.env.isSmall,
        };
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
    convertRecordToEvent(record) {
        return convertRecordToEvent(record);
    }
    getPopoverProps(record) {
        return {
            record,
            model: this.model,
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
        const record = this.model.records[info.event.id];
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
    onDblClick(info) {
        const record = this.model.records[info.event.id];
        if (!record) {
            return;
        }
        this.props.editRecord(record);
    }
    /**
     * @param {boolean} fire
     */
    cancelPendingClick(fire) {
        browser.clearTimeout(this.clickTimeoutId);
        this.clickTimeoutId = null;
        this.pendingClickEventId = null;
        const pending = this.pendingClick;
        this.pendingClick = null;
        if (fire) {
            pending?.();
        }
    }
    onEventClick(info) {
        if (this.clickTimeoutId) {
            if (info.event.id === this.pendingClickEventId) {
                this.cancelPendingClick(false);
                this.onDblClick(info);
                return;
            }
            this.cancelPendingClick(true);
        }
        this.pendingClickEventId = info.event.id;
        this.pendingClick = () => {
            if (!info.el.isConnected) {
                info.el =
                    this.fc.api.el.querySelector(
                        this.computeEventSelector(info.event),
                    ) || info.el;
            }
            this.onClick(info);
        };
        this.clickTimeoutId = browser.setTimeout(
            () => this.cancelPendingClick(true),
            250,
        );
    }
    onEventContent(arg) {
        const { event } = arg;
        if (event.start && event.end) {
            const dateFmt = (date) => fromFcDate(date).toFormat(this.timeFormat);
            arg.timeText = `${dateFmt(event.start)} - ${dateFmt(event.end)}`;
        }
        const record = this.model.records[event.id];
        if (record) {
            const fragment = renderToFragment(
                /** @type {any} */ (this.constructor).eventTemplate,
                {
                    ...record,
                    startTime: this.getStartTime(record),
                    endTime: this.getEndTime(record),
                },
            );
            return { domNodes: [...fragment.children] };
        }
        return true;
    }
    eventClassNames(info) {
        const record = this.model.records[info.event.id];
        const classesToAdd = super.eventClassNames(info);

        if (record) {
            if (record.duration <= 0.25) {
                classesToAdd.push("o_event_oneliner");
            }
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
        super.onDayCellDidMount(info);
        this.injectMobileWeekNumber(info);
    }
    /**
     * @param {Object} info
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
        super.onEventDidMount(info);
        const { el, event } = info;
        const record = this.model.records[event.id];

        if (record) {
            if (record.isMonth) {
                el.querySelector(".fc-event-main").classList.add(
                    "d-flex",
                    "gap-1",
                    "text-truncate",
                );
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
        const start = fromFcDate(event.start);
        let end = fromFcDate(event.end);
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
        const record = this.fcEventToRecord(info.event);
        if (!record) {
            info.revert?.();
            return;
        }
        this.model.updateRecord(record, {
            moved: true,
        });
    }
    onEventResize(info) {
        this.fc.api.unselect();
        const record = this.fcEventToRecord(info.event);
        if (!record) {
            info.revert?.();
            return;
        }
        this.model.updateRecord(record);
    }
    /**
     * @param {Object} event
     * @returns {Object|null}
     */
    fcEventToRecord(event) {
        const { id, allDay, date, start, end } = event;
        const res = {
            start: fromFcDate(date || start),
            isAllDay: allDay,
        };
        if (end) {
            res.end = fromFcDate(end);
            if (["day", "week", "month"].includes(this.model.scale) && allDay) {
                res.end = res.end.minus({ days: 1 });
            }
        }
        if (id) {
            const existingRecord = this.model.records[id];
            if (!existingRecord) {
                return null;
            }
            if (this.model.scale === "month") {
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
        const scale = this.model.scale;
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
