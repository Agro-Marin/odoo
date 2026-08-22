// @ts-check
/** @odoo-module native */

import { loadCSS } from "@web/core/assets";
import { makeLazyFacade } from "@web/core/module_bridge";

/** @type {any} */
let _fullCalendar = null;

/**
 * @type {any}
 */
export const FullCalendar = makeLazyFacade(() => _fullCalendar);

/** @type {Promise<any> | null} */
let loadPromise = null;

/**
 * @returns {Promise<any>}
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
