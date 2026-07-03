// @ts-check
/** @odoo-module native */

/** @module @web/core/lib/fullcalendar - Lazy ESM loader for FullCalendar v7 (+ locales, skeleton CSS) */

import { loadCSS } from "@web/core/assets";

// FullCalendar is the fork-patched v7 vanilla bundle re-exported as a real ES
// module (`static/lib/fullcalendar/fullcalendar.esm.js`), resolved through the
// `@fullcalendar/core` import-map entry as an external bare specifier.  Its
// exported `Calendar` already pre-registers the five default plugins
// (dayGrid/timeGrid/interaction/list/multiMonth), so callers do NOT pass a
// `plugins` option.  Replaces the old `web.fullcalendar_lib` bundle of classic
// `<script>`s that assigned `window.FullCalendar`.

/**
 * Live-bound FullCalendar namespace (`{ Calendar, ProtectedStyles, Shared, ... }`).
 *
 * `null` until {@link loadFullCalendar} has resolved at least once; thereafter
 * importers read the loaded namespace through the ES-module live binding, so
 * existing `FullCalendar.Calendar` / `FullCalendar.ProtectedStyles` call sites
 * keep working after the load with no further change.
 *
 * @type {any}
 */
export let FullCalendar = null;

/** @type {Promise<any> | null} de-dupes concurrent loads into one fetch. */
let loadPromise = null;

/**
 * Lazily load FullCalendar v7, its bundled locales, and the skeleton CSS, then
 * populate the live-bound {@link FullCalendar} export.
 *
 * The locale bundle pushes its locales into the SAME `Shared` registry the
 * core module exposes (both resolve to one URL through the import map), so the
 * loaded namespace is fully locale-aware once this resolves.
 *
 * @returns {Promise<any>} the FullCalendar namespace
 */
export async function loadFullCalendar() {
    if (!FullCalendar) {
        loadPromise ??= (async () => {
            const [coreModule] = await Promise.all([
                import("@fullcalendar/core"),
                import("@fullcalendar/core/locales-all"),
                loadCSS("/web/static/lib/fullcalendar/skeleton.css"),
            ]);
            FullCalendar = coreModule;
            return FullCalendar;
        })().catch((error) => {
            // Never cache a rejection: a transient fetch failure would
            // otherwise disable every future calendar until a full page
            // reload (the pre-ESM loadJS path also allowed retries).
            loadPromise = null;
            throw error;
        });
        await loadPromise;
    }
    return FullCalendar;
}
