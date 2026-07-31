// @ts-check
/** @odoo-module native */

/** @module @web/views/calendar/calendar_view */

import { registry } from "@web/core/registry";

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
    props: (props, view) => {
        const { ArchParser } = view;
        const { arch, relatedModels, resModel } = props;
        const archInfo = new ArchParser().parse(arch, relatedModels, resModel);
        return {
            ...props,
            Model: view.Model,
            Renderer: view.Renderer,
            buttonTemplate: view.buttonTemplate,
            archInfo,
        };
    },
};

registry.category("views").add("calendar", calendarView);
