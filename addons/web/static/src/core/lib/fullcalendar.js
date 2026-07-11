// @ts-check
/** @odoo-module native */

/** @module @web/core/lib/fullcalendar - Lazy ESM loader for FullCalendar v7 (+ locales, skeleton CSS) */

import { loadCSS } from "@web/core/assets";
import { makeLazyFacade } from "@web/core/module_bridge";

// Fork-patched v7 vanilla bundle re-exported as an ES module via the
// `@fullcalendar/core` import map. `Calendar` pre-registers the five default
// plugins (dayGrid/timeGrid/interaction/list/multiMonth), so callers must NOT
// pass a `plugins` option. Replaces the old `window.FullCalendar` script bundle.

/** @type {any} the loaded namespace, null until {@link loadFullCalendar} resolves */
let _fullCalendar = null;

/**
 * Stable facade over the lazily-loaded FullCalendar namespace
 * (`{ Calendar, ProtectedStyles, Shared, ... }`): property reads forward to
 * the loaded namespace, so existing call sites keep working — including
 * through module bridges (iframe bundles), which snapshot exported values
 * and would never see a mutable `export let` reassignment (see the bridge
 * contract in `@web/core/module_bridge`). Callers must still
 * `await loadFullCalendar()` before use.
 *
 * @type {any}
 */
export const FullCalendar = makeLazyFacade(() => _fullCalendar);

/** @type {Promise<any> | null} de-dupes concurrent loads into one fetch. */
let loadPromise = null;

/**
 * Lazily load FullCalendar v7, its bundled locales, and the skeleton CSS,
 * then populate the {@link FullCalendar} facade.
 *
 * The locale bundle pushes into the same `Shared` registry the core module
 * exposes, so the loaded namespace is fully locale-aware once this resolves.
 *
 * @returns {Promise<any>} the FullCalendar namespace (facade)
 */
export async function loadFullCalendar() {
    if (!_fullCalendar) {
        loadPromise ??= (async () => {
            const [coreModule] = await Promise.all([
                import("@fullcalendar/core"),
                import("@fullcalendar/core/locales-all"),
                loadCSS("/web/static/lib/fullcalendar/skeleton.css"),
            ]);
            _fullCalendar = coreModule;
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
