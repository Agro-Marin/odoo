// @ts-check
/** @odoo-module native */

import { Component } from "@odoo/owl";

import { baseEventClassNames, paintMountedEvent } from "./calendar_utils.js";
import {
    decorateFcViewMount,
    fromFcDate,
    withDayCellClassNames,
} from "./hooks/full_calendar_hook.js";

export class CalendarRendererBase extends Component {
    /**
     * @param {{ el: HTMLElement, options: Record<string, any> }} params
     */
    viewDidMount({ el, options }) {
        decorateFcViewMount({
            el,
            fcOptions: options,
            weekNumbers: this.options.weekNumbers,
            weekNumbersWithinDays: this.customOptions.weekNumbersWithinDays,
        });
    }

    /**
     * @param {{ date: any }} info
     * @returns {string[]}
     */
    getDayCellClassNames(info) {
        const date = fromFcDate(info.date).toISODate();
        if (this.model.unusualDays.includes(date)) {
            return ["o_calendar_disabled"];
        }
        return [];
    }

    /**
     * @param {{ date: any }} info
     */
    dayCellClass(info) {
        return withDayCellClassNames(info, this.getDayCellClassNames(info));
    }

    /**
     * @returns {Object[]}
     */
    mapRecordsToEvents() {
        return Object.values(this.model.records).map((r) =>
            this.convertRecordToEvent(r),
        );
    }

    /**
     * @abstract
     * @param {Object} _record
     * @returns {Object}
     */
    convertRecordToEvent(_record) {
        throw new Error(
            `${this.constructor.name} must implement convertRecordToEvent()`,
        );
    }

    /**
     * @param {{ event: { id: string } }} info
     * @returns {string[]}
     */
    eventClassNames({ event }) {
        return baseEventClassNames(this.model.records[event.id]);
    }

    /**
     * @param {{ el?: HTMLElement, date: any }} info
     */
    onDayCellDidMount(info) {
        const classes = this.getDayCellClassNames(info);
        if (classes.length && info.el) {
            info.el.classList.add(...classes);
        }
    }

    /**
     * @param {{ el: HTMLElement, event: { id: string } }} info
     */
    onEventDidMount(info) {
        const { el, event } = info;
        const record = this.model.records[event.id];
        paintMountedEvent(el, event, record, this.eventClassNames(info));
    }
}
