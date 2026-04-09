/**
 * ESM wrapper for FullCalendar UMD packages.
 *
 * Loads the self-contained UMD builds which set ``globalThis.FullCalendar``
 * and its plugin namespaces (DayGrid, TimeGrid, Interaction, List, Luxon3).
 * Re-exports the Calendar constructor as a named ESM export.
 *
 * The luxon3 plugin requires ``globalThis.luxon`` — this wrapper imports
 * luxon from ESM and sets the global before loading the plugin.
 */

// Ensure globalThis.luxon is set for the luxon3 FullCalendar plugin.
// Uses the direct URL path (not bare specifier "luxon") so this wrapper
// works on ALL pages, including test pages without an import map.
import * as luxon from "/web/static/lib/luxon/luxon.mjs";
if (!globalThis.luxon) {
    globalThis.luxon = luxon;
}

const FC_SCRIPTS = [
    "/web/static/lib/fullcalendar/core/index.global.js",
    "/web/static/lib/fullcalendar/core/locales-all.global.js",
    "/web/static/lib/fullcalendar/interaction/index.global.js",
    "/web/static/lib/fullcalendar/daygrid/index.global.js",
    "/web/static/lib/fullcalendar/luxon3/index.global.js",
    "/web/static/lib/fullcalendar/timegrid/index.global.js",
    "/web/static/lib/fullcalendar/list/index.global.js",
];

if (!globalThis.FullCalendar) {
    // Load scripts sequentially (plugins depend on core being loaded first).
    for (const src of FC_SCRIPTS) {
        await new Promise((resolve, reject) => {
            const script = document.createElement("script");
            script.src = src;
            script.onload = resolve;
            script.onerror = reject;
            document.head.appendChild(script);
        });
    }
}

const { Calendar } = globalThis.FullCalendar;
export { Calendar };
export default globalThis.FullCalendar;
