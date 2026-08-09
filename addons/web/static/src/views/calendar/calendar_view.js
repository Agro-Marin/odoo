// @ts-check
/** @odoo-module native */

/** @module @web/views/calendar/calendar_view */

import { registry } from "@web/core/registry";
import { defaultViewProps } from "@web/views/view_utils";

import { CalendarArchParser } from "./calendar_arch_parser.js";
import { CalendarController } from "./calendar_controller.js";
import { CalendarModel } from "./calendar_model.js";
import { CalendarRenderer } from "./calendar_renderer.js";
export const calendarView = {
    type: "calendar",

    searchMenuTypes: ["filter", "favorite"],

    ArchParser: CalendarArchParser,
    Controller: CalendarController,
    Model: CalendarModel,
    Renderer: CalendarRenderer,

    buttonTemplate: "web.CalendarController.controlButtons",

    /**
     * @param {Record<string, any>} props
     * @param {Record<string, any>} view
     * @returns {Record<string, any>}
     */
    // Exactly the shared projection, with nothing of its own to add.
    props: defaultViewProps,
};

registry.category("views").add("calendar", calendarView);
