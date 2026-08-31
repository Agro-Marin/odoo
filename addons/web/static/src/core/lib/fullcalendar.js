// @ts-check
/** @odoo-module native */

import { loadCSS } from "@web/core/assets";
import { makeLazyLib } from "@web/core/lib/lazy_lib";

const fullCalendar = makeLazyLib(async () => {
    const [coreModule] = await Promise.all([
        import("@fullcalendar/core"),
        import("@fullcalendar/core/locales-all"),
        loadCSS("/web/static/lib/fullcalendar/skeleton.css"),
    ]);
    return coreModule;
});

/** @type {any} */
export const FullCalendar = fullCalendar.facade;

/**
 * @returns {Promise<any>}
 */
export function loadFullCalendar() {
    return fullCalendar.load();
}
