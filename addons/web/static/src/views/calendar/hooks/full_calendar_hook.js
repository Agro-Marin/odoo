// @ts-check
/** @odoo-module native */

/** @module @web/views/calendar/hooks/full_calendar_hook - Hook managing FullCalendar instance lifecycle (load, render, refresh, destroy) */

import {
    onMounted,
    onPatched,
    onWillStart,
    onWillUnmount,
    useComponent,
    useRef,
} from "@odoo/owl";
import { DateTime, IANAZone, Settings } from "@web/core/l10n/luxon";
/**
 * OWL hook that manages a FullCalendar instance lifecycle: loads the bundle,
 * creates/renders on mount, refreshes on patch, destroys on unmount.
 *
 * @param {string} refName - OWL template ref name for the calendar container element
 * @param {Object} params - FullCalendar configuration options (functions are bound to the component)
 * @returns {{ api: FullCalendar.Calendar, el: HTMLElement }} accessor for the calendar instance and DOM element
 */
import { FullCalendar, loadFullCalendar } from "@web/core/lib/fullcalendar";

/**
 * Returns a time-zone identifier safe to pass to ``new Calendar({ timeZone })``.
 *
 * FullCalendar v7 forwards the value to ``Intl.DateTimeFormat({ timeZone })``,
 * which only accepts IANA names (``UTC``, ``Europe/Brussels``, ...) — not Luxon's
 * ``FixedOffsetZone`` names like ``"UTC+1"``. For those we translate the
 * offset into the equivalent POSIX ``Etc/GMT±N`` IANA name (sign inverted:
 * UTC+2 -> ``Etc/GMT-2``), keeping FC's date arithmetic and Intl-based
 * formatting on the same zone so markers round-trip without drift. Earlier
 * attempts returning ``"UTC"`` or the magic ``"local"`` unchanged broke
 * day-boundary alignment / event-time formatting for non-zero offsets —
 * kept here as a warning against reintroducing them.
 *
 * Zones are classified by Luxon zone TYPE, never by name shape: slash-less
 * IANA zones with working DST (``CET``, ``EET``, ``GB``, ``NZ``, ``Israel``,
 * ...) are just as IANA as ``Europe/Brussels`` and MUST pass through by
 * name. An earlier ``name.includes("/")`` check dropped them into the
 * fixed-offset path below, freezing ``zone.offset(0)`` (January 1970) for
 * the whole year — a CET user in summer (CEST, +02:00) got a calendar
 * aligned to ``Etc/GMT-1``: every event rendered an hour early and drags
 * wrote back shifted times.
 *
 * :return: a time-zone identifier accepted by FullCalendar v7
 * :rtype: string
 */
export function getFullCalendarTimeZone() {
    const zone = Settings.defaultZone;
    const name = zone.name;
    // ``iana``-typed zones carry an IANA name by construction; the
    // ``system`` zone's name is Intl's resolved identifier. Both pass
    // through when Intl can actually resolve the name (``isValidZone``
    // guards invalid IANAZone instances and exotic system names).
    if (
        typeof name === "string" &&
        (zone.type === "iana" || zone.type === "system") &&
        IANAZone.isValidZone(name)
    ) {
        return name;
    }
    // Fixed-offset zones (and anything unresolvable above) follow the
    // POSIX ``Etc/GMT±N`` translation — this is the ``mockTimeZone(±N)``
    // test path.
    // zone.offset(0): minutes from UTC (no DST). IANA's ``Etc/GMT±N`` only
    // covers integer-hour offsets in [-12, +14] (``Etc/zone.tab``); outside
    // that range (e.g. ``mockTimeZone(±40)`` in tests) fall back to
    // ``"local"`` — ``fcEventToRecord`` already handles marker conversion
    // for that case.
    if (typeof zone.offset === "function") {
        const offsetMinutes = zone.offset(0);
        if (Number.isFinite(offsetMinutes) && offsetMinutes % 60 === 0) {
            const hours = offsetMinutes / 60;
            if (hours === 0) {
                return "UTC";
            }
            if (hours >= -12 && hours <= 14) {
                // POSIX inversion: positive UTC offset → Etc/GMT-N.
                return hours > 0 ? `Etc/GMT-${hours}` : `Etc/GMT+${-hours}`;
            }
        }
    }
    return "local";
}

/**
 * Convert a Date received from FullCalendar into a Luxon DateTime in the
 * user's zone, marker-aware.
 *
 * FC v7 emits two Date conventions depending on its ``timeZone`` option (see
 * ``getFullCalendarTimeZone``):
 *
 * - IANA/named zone: a real-epoch Date — ``fromJSDate`` reads it correctly.
 * - ``"local"`` (FixedOffsetZone defaults that miss the ``Etc/GMT±N`` path):
 *   a MARKER Date whose UTC components encode the visible local-clock time,
 *   not the real instant. ``fromJSDate`` would apply the offset a second
 *   time (e.g. a cell at local midnight in a negative-offset zone lands on
 *   the previous day). Rebuild from UTC components instead, truncated to the
 *   minute — markers picked up during drag gestures can carry sub-minute
 *   drift from the (mocked) clock, meaningless on a 15-min snap grid.
 *
 * Use this for every ``info.date``/``event.start`` consumer (day-cell
 * classes, week numbers, headers, record conversion), not just
 * ``fcEventToRecord``. See fullcalendar.esm.js (``timestampToMarker`` /
 * ``toDate``) for the FC-side conversion mirrored here.
 *
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

/**
 * Class-name generator for FullCalendar's ``dayCellClass`` option that
 * re-injects v6-compatible state classes (``fc-day``, ``fc-day-other``,
 * ``fc-day-today``, ``fc-day-past``, ``fc-day-future``, ``fc-day-disabled``)
 * on top of v7's hashed class names.
 *
 * v7's render-props payload exposes ``isOther`` / ``isToday`` / ``isPast``
 * / ``isFuture`` / ``isDisabled`` flags per cell.  Returns a space-joined
 * string — FC v7's ``joinClassNames`` does ``.filter(Boolean).join(" ")``,
 * which stringifies arrays via comma-toString and produces broken class
 * names like ``"fc-day,fc-day-today"``.
 *
 * :param info: cell render-props supplied by FullCalendar
 * :return: space-joined v6-compatible day-cell class names
 * :rtype: string
 */
export function dayCellClassNames(info) {
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
    // v6 carried ``fc-daygrid-day`` on every day cell (month-view cells and
    // the all-day strip cells of a timegrid week/day view); v7 dropped it.
    // Re-add unconditionally: tests select compound selectors like
    // ``.fc-daygrid-day.o_calendar_disabled`` from both contexts, and
    // ``fc-day`` alone doesn't cover that. Timegrid SLOT cells use
    // ``dayLaneClass`` instead — they don't hit this generator.
    classes.push("fc-daygrid-day");
    // v6 also carried ``fc-day-<short-weekday>`` per cell. v7 dropped it but
    // exposes ``info.dow`` (0=Sunday..6=Saturday) — see
    // ``fullcalendar.esm.js`` (``getDateMeta``). Derive the suffix from
    // ``dow`` directly, independent of timezone-marker handling on ``info.date``.
    if (Number.isInteger(info?.dow) && info.dow >= 0 && info.dow < 7) {
        const SHORT_WEEKDAY = ["sun", "mon", "tue", "wed", "thu", "fri", "sat"];
        classes.push(`fc-day-${SHORT_WEEKDAY[info.dow]}`);
    }
    return classes.join(" ");
}

/**
 * Class-name generator for FullCalendar's ``dayHeaderClass`` option.
 *
 * v6's column headers carried BOTH ``fc-col-header-cell`` AND ``fc-day``
 * on the same element, plus per-state suffixes.  v7's hashed names hide
 * the v6 hooks, so we re-inject them.  Tests target compound selectors
 * like ``.fc-col-header-cell.fc-day`` so both classes must live on the
 * same element.
 *
 * :param info: header render-props supplied by FullCalendar
 * :return: space-joined v6-compatible header class names
 * :rtype: string
 */
export function dayHeaderClassNames(info) {
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
 * Resolve one of FullCalendar v7's build-hashed internal class names
 * (e.g. ``"internalScroller"`` -> ``"fc-7a"``) for the loaded library build.
 *
 * v7 regenerates these hashes on every build, so hard-coding them
 * (``".fc-1i"``) breaks on each bump; resolve through the public
 * ``ProtectedStyles`` name->hash map instead. Must be called after
 * ``web.fullcalendar_lib`` has loaded, when ``FullCalendar`` is available.
 *
 * @param {string} name internal class-name key from FC's ``classNames`` map
 * @returns {string} the hashed class name for the loaded build
 */
export function fcInternalClassName(name) {
    return FullCalendar.ProtectedStyles.default[name];
}

/**
 * Cheap identity of the calendar's current event set (id + range), used to
 * decide whether the year view needs its synchronous rebuild after
 * ``refetchEvents``.
 *
 * @param {any} instance FullCalendar Calendar
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
        // Never let the fingerprint break the patch cycle — an error here
        // forces the rebuild.
        return `error:${Date.now()}`;
    }
}

export function useFullCalendar(refName, paramsOrGetter) {
    const component = useComponent();
    const ref = useRef(refName);
    let instance = null;

    // ``params`` may be the literal options object captured at setup time
    // OR a function/getter that returns a fresh options object on every
    // call.  In v7 we need fresh values on every ``onPatched`` (the
    // renderer's ``initialDate`` / ``initialView`` change when the OWL
    // ``scale`` prop updates).  Accepting a getter lets callers stay on
    // the existing ``this.options`` accessor pattern without forcing them
    // to allocate a new object on every render.
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

    // Block body so the arrow returns ``Promise<void>`` rather than the
    // bundle loader's ``Promise<void[]>`` (same idiom as
    // ``components/code_editor/code_editor.js``).
    onWillStart(async () => {
        await loadFullCalendar();
    });

    onMounted(() => {
        try {
            // v7's ``Calendar`` wrapper already pre-injects the five default
            // plugins (dayGrid/timeGrid/interaction/list/multiMonth — see
            // fullcalendar.esm.js); callers don't pass ``plugins``.
            // Mark the FC root as portal host BEFORE construction so the
            // fork-local ``getAppendableRoot`` override (fullcalendar.esm.js)
            // routes MorePopover/ElementMirror here instead of <body>, which
            // sits outside the test fixture's query scope.
            ref.el.setAttribute("data-fc-portal-host", "true");
            const mountParams = boundParams();
            instance = new FullCalendar.Calendar(ref.el, mountParams);
            // Seed the no-op-gotoDate guard with the initial anchor so the
            // first ``onPatched`` doesn't re-issue gotoDate for the same
            // date and reset scrollTop via FC v7's componentDidUpdate path.
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
        // v7 only honours options that mutate via the explicit API, so switch
        // the view manually when the OWL component's scale prop changes.
        //
        // Order matters: ``changeView(view, date)`` must set both atomically
        // — separate ``changeView`` + ``gotoDate`` calls trigger two render
        // passes, briefly landing on the wrong (previous) date and dropping
        // out-of-range events. ``refetchEvents`` runs last so it fetches for
        // the correct, post-change date window.
        const currentViewType = instance.view?.type;
        const targetView =
            typeof params.initialView === "string" ? params.initialView : null;
        const targetDate =
            typeof params.initialDate !== "undefined" ? params.initialDate : null;
        // Whether the view type or displayed date window moved this patch; the
        // refetch below is gated on it (plus a records-identity change) so
        // render-only patches (sidebar toggle, popover open/close,
        // multi-select) don't rebuild FullCalendar's entire event store.
        let viewOrDateChanged = false;
        if (targetView && currentViewType && currentViewType !== targetView) {
            try {
                instance.changeView(targetView, targetDate);
            } catch {
                // Fall back to the legacy two-step path if changeView
                // rejects the date payload (unusual range types).
                instance.changeView(targetView);
                if (targetDate) {
                    try {
                        instance.gotoDate(targetDate);
                    } catch {
                        // Bad date — leave the calendar at its current position.
                    }
                }
            }
            instance.__lastInitialDate = targetDate;
            viewOrDateChanged = true;
        } else if (targetDate && targetDate !== instance.__lastInitialDate) {
            // v7's ``gotoDate`` resets the timegrid scroll to ``scrollTime``
            // even when called with the SAME date (FC's ``scrollTimeReset``
            // still produces a new ``dateProfile``), clobbering any
            // ``scrollToTime`` on a no-op date change (e.g. "Today" while
            // already on today). Track the last issued date and skip the
            // redundant call to preserve scroll position; a scale change
            // still updates ``__lastInitialDate`` via ``changeView`` above.
            try {
                instance.gotoDate(targetDate);
                instance.__lastInitialDate = targetDate;
                viewOrDateChanged = true;
            } catch {
                // Bad date string — keep current position.
            }
        }
        // The model rebuilds its records object on every (re)load (filter
        // toggle, date move, another session's change), so an identity change
        // is the reliable "events may differ" signal. Render-only patches keep
        // the same reference and can skip the whole refetch/fingerprint pass.
        const recordsChanged = instance.__lastRecords !== component.props.model.records;
        instance.__lastRecords = component.props.model.records;
        if (viewOrDateChanged || recordsChanged) {
            const eventsBefore =
                component.props.model.scale === "year"
                    ? eventSetFingerprint(instance)
                    : "";
            instance.refetchEvents();
            // Year view renders events as background events; v7 schedules their
            // re-render asynchronously, so after a filter toggle stale
            // ``.fc-bg-event`` nodes linger until the next frame unless we force
            // a synchronous destroy+render here.
            //
            // Gated on an actual event-set change: the year renderer holds 12
            // hook instances, and an unconditional destroy+render on every OWL
            // patch meant 12 full FC rebuild cycles per patch.
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
        // When onMounted threw (e.g. v7 rejected the time-zone before
        // ``new Calendar`` returned) ``instance`` stays null; destroy
        // would then NPE and mask the original error message.
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
