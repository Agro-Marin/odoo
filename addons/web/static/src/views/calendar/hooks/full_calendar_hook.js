// @ts-check
/** @odoo-module native */

import {
    onMounted,
    onPatched,
    onWillStart,
    onWillUnmount,
    useComponent,
    useRef,
} from "@odoo/owl";
import { DateTime, IANAZone, Settings } from "@web/core/l10n/luxon";
import { FullCalendar, loadFullCalendar } from "@web/core/lib/fullcalendar";
import { makeWeekColumn } from "@web/views/calendar/calendar_common/calendar_common_week_column";

export function getFullCalendarTimeZone() {
    const zone = Settings.defaultZone;
    const name = zone.name;
    if (
        typeof name === "string" &&
        (zone.type === "iana" || zone.type === "system") &&
        IANAZone.isValidZone(name)
    ) {
        return name;
    }
    if (typeof zone.offset === "function") {
        const offsetMinutes = zone.offset(0);
        if (Number.isFinite(offsetMinutes) && offsetMinutes % 60 === 0) {
            const hours = offsetMinutes / 60;
            if (hours === 0) {
                return "UTC";
            }
            if (hours >= -12 && hours <= 14) {
                return hours > 0 ? `Etc/GMT-${hours}` : `Etc/GMT+${-hours}`;
            }
        }
    }
    return "local";
}

/**
 * @param {Date} date
 * @returns {import("@web/core/l10n/luxon").DateTime}
 */
export function fromFcDate(date) {
    if (getFullCalendarTimeZone() !== "local") {
        return DateTime.fromJSDate(date);
    }
    return DateTime.fromObject({
        year: date.getUTCFullYear(),
        month: date.getUTCMonth() + 1,
        day: date.getUTCDate(),
        hour: date.getUTCHours(),
        minute: date.getUTCMinutes(),
    });
}

function dayCellClassNames(info) {
    const classes = ["fc-day"];
    if (info?.isOther) {
        classes.push("fc-day-other");
    }
    if (info?.isToday) {
        classes.push("fc-day-today");
    }
    if (info?.isPast) {
        classes.push("fc-day-past");
    }
    if (info?.isFuture) {
        classes.push("fc-day-future");
    }
    if (info?.isDisabled) {
        classes.push("fc-day-disabled");
    }
    classes.push("fc-daygrid-day");
    if (Number.isInteger(info?.dow) && info.dow >= 0 && info.dow < 7) {
        const SHORT_WEEKDAY = ["sun", "mon", "tue", "wed", "thu", "fri", "sat"];
        classes.push(`fc-day-${SHORT_WEEKDAY[info.dow]}`);
    }
    return classes.join(" ");
}

/**
 * @param {any} info
 * @param {string[]} extras
 * @returns {string}
 */
export function withDayCellClassNames(info, extras) {
    const base = dayCellClassNames(info);
    return extras.length ? `${base} ${extras.join(" ")}` : base;
}

/**
 * @param {{
 * el: HTMLElement,
 * fcOptions: Record<string, any> | undefined,
 * weekNumbers: boolean,
 * weekNumbersWithinDays: boolean,
 * }} params
 * @returns {void}
 */
export function decorateFcViewMount({
    el,
    fcOptions,
    weekNumbers,
    weekNumbersWithinDays,
}) {
    if (!fcOptions) {
        return;
    }
    if (weekNumbers && !weekNumbersWithinDays) {
        makeWeekColumn(
            /** @type {any} */ ({
                el,
                weekText: fcOptions.weekTextShort ?? "",
            }),
        );
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

/**
 * @param {any} dayCellClass
 * @returns {Record<string, any>}
 */
export function fcViewClassOptions(dayCellClass) {
    return {
        class: "fc",
        viewClass: ({ view }) =>
            view && view.type ? `fc-view fc-${view.type}-view` : "fc-view",
        dayCellClass,
        dayCellInnerClass: "fc-daygrid-day-frame",
        dayCellTopClass: "fc-daygrid-day-top",
        dayCellTopInnerClass: "fc-daygrid-day-number",
        dayHeaderClass: dayHeaderClassNames,
        backgroundEventClass: "fc-bg-event",
    };
}

function dayHeaderClassNames(info) {
    const classes = ["fc-col-header-cell", "fc-day"];
    if (info?.isToday) {
        classes.push("fc-day-today");
    }
    if (info?.isPast) {
        classes.push("fc-day-past");
    }
    if (info?.isFuture) {
        classes.push("fc-day-future");
    }
    return classes.join(" ");
}

/**
 * @param {string} name
 * @returns {string}
 */
export function fcInternalClassName(name) {
    return FullCalendar.ProtectedStyles.default[name];
}

/**
 * @param {any} instance
 * @returns {string}
 */
function eventSetFingerprint(instance) {
    try {
        return instance
            .getEvents()
            .map((e) => `${e.id}:${e.startStr}:${e.endStr}`)
            .sort()
            .join("|");
    } catch {
        return `error:${Date.now()}`;
    }
}

/**
 * @param {string} refName
 * @param {Object} paramsOrGetter
 * @returns {{ api: any, el: HTMLElement | null }}
 */
export function useFullCalendar(refName, paramsOrGetter) {
    const component = useComponent();
    const ref = useRef(refName);
    let instance = null;

    function currentParams() {
        return typeof paramsOrGetter === "function" ? paramsOrGetter() : paramsOrGetter;
    }

    function boundParams() {
        const params = currentParams();
        const newParams = {};
        for (const key of Object.keys(params)) {
            const value = params[key];
            newParams[key] =
                typeof value === "function" ? value.bind(component) : value;
        }
        return newParams;
    }

    onWillStart(async () => {
        await loadFullCalendar();
    });

    onMounted(() => {
        try {
            /** @type {HTMLElement} */ (ref.el).setAttribute(
                "data-fc-portal-host",
                "true",
            );
            const mountParams = boundParams();
            instance = new FullCalendar.Calendar(ref.el, mountParams);
            instance.__lastInitialDate =
                typeof mountParams.initialDate !== "undefined"
                    ? mountParams.initialDate
                    : null;
            instance.render();
        } catch (e) {
            throw new Error(`Cannot instantiate FullCalendar\n${e.message}`, {
                cause: e,
            });
        }
    });

    onPatched(() => {
        const params = currentParams();
        instance.setOption("weekends", component.props.isWeekendVisible);
        const currentViewType = instance.view?.type;
        const targetView =
            typeof params.initialView === "string" ? params.initialView : null;
        const targetDate =
            typeof params.initialDate !== "undefined" ? params.initialDate : null;
        let viewOrDateChanged = false;
        if (targetView && currentViewType && currentViewType !== targetView) {
            try {
                instance.changeView(targetView, targetDate);
            } catch {
                instance.changeView(targetView);
                if (targetDate) {
                    try {
                        instance.gotoDate(targetDate);
                    } catch {}
                }
            }
            instance.__lastInitialDate = targetDate;
            viewOrDateChanged = true;
        } else if (targetDate && targetDate !== instance.__lastInitialDate) {
            try {
                instance.gotoDate(targetDate);
                instance.__lastInitialDate = targetDate;
                viewOrDateChanged = true;
            } catch {}
        }
        const recordsChanged = instance.__lastRecords !== component.props.model.records;
        instance.__lastRecords = component.props.model.records;
        if (viewOrDateChanged || recordsChanged) {
            const eventsBefore =
                component.props.model.scale === "year"
                    ? eventSetFingerprint(instance)
                    : "";
            instance.refetchEvents();
            if (
                component.props.model.scale === "year" &&
                eventsBefore !== eventSetFingerprint(instance)
            ) {
                instance.destroy();
                instance.render();
            }
        }
    });
    onWillUnmount(() => {
        instance?.destroy();
    });

    return {
        get api() {
            return instance;
        },
        get el() {
            return ref.el;
        },
    };
}
