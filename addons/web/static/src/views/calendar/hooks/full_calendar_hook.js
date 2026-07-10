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
import { Settings } from "@web/core/l10n/luxon";
/**
 * OWL hook that manages a FullCalendar instance lifecycle.
 *
 * Loads the FullCalendar library bundle, creates and renders the calendar on
 * mount, refreshes events on patch, and destroys the instance on unmount.
 *
 * @param {string} refName - OWL template ref name for the calendar container element
 * @param {Object} params - FullCalendar configuration options (functions are bound to the component)
 * @returns {{ api: FullCalendar.Calendar, el: HTMLElement }} accessor for the calendar instance and DOM element
 */
import { FullCalendar, loadFullCalendar } from "@web/core/lib/fullcalendar";

/**
 * Returns a time-zone identifier safe to pass to ``new Calendar({ timeZone })``.
 *
 * FullCalendar v7 forwards an IANA-name string to
 * ``new Intl.DateTimeFormat({ timeZone })`` unchanged.  Intl only accepts
 * IANA names (``UTC``, ``Europe/Brussels``, ``Etc/GMT-2``, …).  Luxon's
 * ``Settings.defaultZone`` may be:
 *
 *   - an IANA-named zone (``Europe/Brussels``)
 *   - the literal ``"UTC"``
 *   - a ``FixedOffsetZone`` whose ``.name`` is ``"UTC+1"`` / ``"UTC-9"``
 *     — Intl rejects these names; Luxon's ``DateTime#toISO`` still emits
 *     the matching offset in the ISO string.
 *
 * For the IANA / UTC cases we pass the name straight through so FC's
 * day boundaries align with Luxon's local rendering.  For a
 * ``FixedOffsetZone``, we translate the offset into the matching POSIX
 * ``Etc/GMT±N`` IANA name.  Two earlier strategies and their failure
 * modes (kept here as warnings to future hands):
 *
 *   - Returning ``"UTC"`` broke ``initialDate`` / event-range
 *     alignment whenever the offset was non-zero — events serialized
 *     with ``+01:00`` fell outside FC's UTC-midnight day window.
 *   - Returning the magic value ``"local"`` made FC use native
 *     ``Date`` arithmetic for date math but Intl's local-zone
 *     formatting for ``eventTimeFormat``.  The two diverged in marker
 *     mode: a 06:00-UTC marker for "06:00 local" formatted as
 *     ``getTimezoneOffset() + 06:00`` in local time, shifting every
 *     event-time text by the mock offset (visible as the "10:00 -
 *     12:00" vs expected "08:00 - 10:00" symptom in
 *     ``create event with timezone in week mode European locale``).
 *
 * ``Etc/GMT-N`` is a real IANA zone with no DST and a fixed offset
 * that POSIX inverts (``Etc/GMT-2`` is UTC+2, not UTC-2 — see the
 * POSIX spec footnote in the IANA tzdata).  This keeps FC's date
 * arithmetic AND its Intl-based formatting on the same zone, so
 * markers round-trip through select / display / serialise without
 * the +N-hour drift.
 *
 * :return: a time-zone identifier accepted by FullCalendar v7
 * :rtype: string
 */
export function getFullCalendarTimeZone() {
    const zone = Settings.defaultZone;
    const name = zone.name;
    if (typeof name === "string" && (name === "UTC" || name.includes("/"))) {
        return name;
    }
    // FixedOffsetZone: ``zone.offset(0)`` returns the offset in
    // minutes from UTC for any instant (no DST). POSIX inverts the
    // sign in ``Etc/GMT±N``, so UTC+2 (offset = +120) → ``Etc/GMT-2``.
    //
    // IANA's ``Etc/GMT±N`` covers integer-hour offsets in the
    // ``[-12, +14]`` range (per ``Etc/zone.tab`` in the canonical
    // tzdata). For offsets outside that range — typically tests with
    // ``mockTimeZone(±40)`` to exercise extreme-offset edge cases —
    // fall back to ``"local"``. The fallback re-enables the
    // marker-Date convention (display strings drift by the mocked
    // offset, but date arithmetic stays consistent with Hoot's mocked
    // ``getTimezoneOffset``), which is what those tests rely on for
    // ``write``/``create`` payload assertions. The fork-local
    // ``fcEventToRecord`` already handles the marker conversion when
    // the returned zone is ``"local"``.
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
    // v6 used ``fc-daygrid-day`` on every day cell — both the proper
    // day-grid cells in month view and the all-day strip cells at the
    // top of a timegrid week/day view (which is a single-row daygrid
    // internally).  v7 dropped the class entirely; we layer it back on
    // unconditionally because:
    //   1. Tests select compound classes like
    //      ``.fc-daygrid-day.o_calendar_disabled`` from both contexts.
    //   2. The ``fc-day`` already distinguishes day cells from non-day
    //      content; ``fc-daygrid-day`` is just the v6 alias.
    // Timegrid SLOT cells (hour rows in the time grid body) use
    // ``dayLaneClass`` instead — they don't hit this generator.
    classes.push("fc-daygrid-day");
    // v6 also carried ``fc-day-<short-weekday>`` (sun/mon/tue/wed/thu/
    // fri/sat) on every day cell, derived from the cell date.  v7
    // dropped these but exposes ``info.dow`` (0=Sunday..6=Saturday) in
    // its render-props payload — see ``fullcalendar.esm.js:8367``
    // (``getDateMeta`` populating the spread used by
    // ``dayCellRenderProps``).  Re-inject the v6 short-name suffix
    // from ``dow`` directly to stay independent of timezone-marker
    // gymnastics on ``info.date``.
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
 * v7 hashes its structural class names and regenerates those hashes on every
 * build, so hard-coding them (``".fc-1i"``) silently breaks on each library
 * bump. The public ``ProtectedStyles`` export carries the live name->hash map
 * for the loaded build, so resolving through it keeps the fork's stable-v6-name
 * re-injection working across upgrades with no code changes. Must be called
 * after ``web.fullcalendar_lib`` has loaded (e.g. from a renderer's
 * mount/refresh handler), when the ``FullCalendar`` global is available.
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
        // just forces the rebuild.
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
            // v7's exported ``Calendar`` is a thin wrapper that already
            // pre-injects the five default plugins (dayGrid/timeGrid/
            // interaction/list/multiMonth — see lines ~16956-16973 of
            // ``fullcalendar.esm.js``).  Callers do NOT need to pass
            // ``plugins`` — v6's auto-registration is now built into the
            // wrapper's constructor.
            // Mark the FC root as the portal host BEFORE constructing the
            // calendar so the fork-local override in
            // ``lib/fullcalendar/fullcalendar.esm.js`` (function
            // ``getAppendableRoot``) routes MorePopover and ElementMirror
            // into this element instead of <body>.  Without this, FC
            // portals to document.body which sits outside the test
            // fixture's query scope and the Odoo overlay tree.
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
        // v6 used to react to ``initialView`` changes implicitly; v7's
        // ``Calendar`` only honours options that mutate via the explicit
        // API.  Switch the view when the OWL component's scale prop
        // changes so events re-render in the right grid layout.
        //
        // Order matters in v7:
        //   1. ``changeView(view, date)`` atomically swaps the view AND
        //      sets the focused date — passing both in one call ensures
        //      the new view mounts at the right date.  Separate
        //      ``changeView`` + ``gotoDate`` calls in v7 trigger TWO
        //      render passes, and the first one (after ``changeView``
        //      alone) lands the view on the WRONG date (the previous
        //      view's date), which clears any events fetched into the
        //      out-of-range window.
        //   2. ``refetchEvents`` runs last so the events callback fires
        //      for the correct date range.  In v6, ``refetchEvents``
        //      before view/date changes worked because the fetch was
        //      view-agnostic — v7 ranges fetches by date window.
        const currentViewType = instance.view?.type;
        const targetView =
            typeof params.initialView === "string" ? params.initialView : null;
        const targetDate =
            typeof params.initialDate !== "undefined" ? params.initialDate : null;
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
        } else if (targetDate && targetDate !== instance.__lastInitialDate) {
            // v7's ``gotoDate`` triggers a ``componentDidUpdate`` cycle in
            // ``TimeGridLayoutContents`` that calls ``resetScroll()`` when
            // the ``dateProfile`` changes AND ``scrollTimeReset`` is truthy
            // (FC default).  Calling ``gotoDate`` with the SAME date as the
            // current view still produces a new ``dateProfile`` instance
            // and resets the timegrid scroll back to ``scrollTime`` (06:00
            // by default).  That clobbers any ``scrollToTime`` we issue
            // alongside a no-op date change (e.g. clicking "Today" while
            // already on today, or any ``model.load`` that leaves the date
            // unchanged like a filter toggle).
            //
            // Track the last issued ``initialDate`` and skip the redundant
            // ``gotoDate`` so the scroll position is preserved.  A scale
            // change still goes through ``changeView`` above, which sets
            // ``__lastInitialDate`` to the new view's anchor.
            try {
                instance.gotoDate(targetDate);
                instance.__lastInitialDate = targetDate;
            } catch {
                // Bad date string — keep current position.
            }
        }
        const eventsBefore =
            component.props.model.scale === "year" ? eventSetFingerprint(instance) : "";
        instance.refetchEvents();
        // Year view renders events as ``display: "background"``.  After a
        // filter toggle v7 schedules the bg-event re-render asynchronously,
        // so ``refetchEvents`` alone leaves the previous ``.fc-bg-event``
        // nodes (and their ``data-event-id``) in the DOM until the next
        // frame — observable as stale events right after an awaited filter
        // change.  Force a synchronous re-render so the DOM matches the model
        // within the OWL patch.  (The earlier ``params.weekNumbers`` guard
        // never fired: the year renderer sets ``weekNumbers: false``.)
        //
        // Gated on an actual event-set change: the year renderer holds 12
        // hook instances and EVERY OWL patch (weekend toggle, unusual-days
        // arrival, any model notify) lands here — an unconditional
        // destroy+render meant 12 full FullCalendar teardown/rebuild cycles
        // per patch. Prop-only patches now skip the rebuild.
        if (
            component.props.model.scale === "year" &&
            eventsBefore !== eventSetFingerprint(instance)
        ) {
            instance.destroy();
            instance.render();
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
