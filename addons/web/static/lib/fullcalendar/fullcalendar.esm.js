// ESM facade over the vendored FullCalendar v7 IIFE bundle.
//
// The upstream v7 distribution ships only ``fullcalendar.global.js`` (a
// classic-script IIFE that assigns ``var FullCalendar = …`` at the top
// level).  Loaded via a regular ``<script>`` tag — the path used by
// ``web.fullcalendar_lib`` for the OWL calendar view — that ``var``
// becomes ``window.FullCalendar`` and everything works.
//
// Enterprise's planning website widget at
// ``enterprise/planning/static/src/js/planning_calendar_front.js`` reaches
// for the library via a dynamic ``import()`` at this URL instead.  ES
// modules parse the same source with module-scoped ``var`` semantics, so
// the IIFE's ``FullCalendar`` would never escape to the global scope and
// ``import {Calendar}`` from this URL would return ``undefined``.
//
// This facade closes the gap: it loads the IIFE through a classic-script
// tag (which DOES assign to the global), waits for it to evaluate, and
// re-exports the public surface so dynamic-import callers get the same
// ``Calendar`` constructor backend callers receive.
if (!globalThis.FullCalendar) {
    await new Promise((resolve, reject) => {
        const script = document.createElement("script");
        script.src = new URL("./fullcalendar.global.js", import.meta.url).href;
        script.onload = resolve;
        script.onerror = () =>
            reject(new Error("Failed to load fullcalendar.global.js"));
        document.head.appendChild(script);
    });
}
// v6's global bundle auto-registered the view plugins; v7 exposes them
// as individual named exports the caller must wire into ``new Calendar``'s
// ``plugins`` option.  Re-export the namespaces AND the actual plugin
// objects (``.default`` of each namespace) so dynamic-import callers can
// reach either flavour without poking at ``globalThis.FullCalendar``.
export const { Calendar, DayGrid, TimeGrid, Interaction, List, MultiMonth } =
    globalThis.FullCalendar;
export const dayGridPlugin = DayGrid.default;
export const timeGridPlugin = TimeGrid.default;
export const interactionPlugin = Interaction.default;
export const listPlugin = List.default;
export const multiMonthPlugin = MultiMonth.default;
