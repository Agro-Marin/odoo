// @ts-check
/** @odoo-module native */

/** @module @web/core/lib/fullcalendar - Lazy ESM loader for FullCalendar v7 (+ locales, skeleton CSS) */

import { loadCSS } from "@web/core/assets";
import { makeLazyFacade } from "@web/core/module_bridge";

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
            loadPromise = null;
            throw error;
        });
        await loadPromise;
    }
    return FullCalendar;
}
