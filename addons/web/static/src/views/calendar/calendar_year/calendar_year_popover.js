// @ts-check
/** @odoo-module native */

import { Component } from "@odoo/owl";
import { formatDate } from "@web/core/l10n/dates";
import { Dialog } from "@web/ui/dialog/dialog";
import { getColor, getFormattedDateSpan } from "@web/views/calendar/calendar_utils";

export class CalendarYearPopover extends Component {
    static components = { Dialog };
    static template = "web.CalendarYearPopover";
    static subTemplates = {
        popover: "web.CalendarYearPopover.popover",
        body: "web.CalendarYearPopover.body",
        footer: "web.CalendarYearPopover.footer",
        record: "web.CalendarYearPopover.record",
    };
    static props = {
        close: Function,
        date: true,
        model: Object,
        records: Array,
        createRecord: Function,
        deleteRecord: Function,
        editRecord: Function,
    };

    /** @returns {Array<{ title: string, start: Object, end: Object, records: Object[] }>} */
    get recordGroups() {
        return this.computeRecordGroups();
    }

    /** @returns {string} */
    get dialogTitle() {
        return formatDate(this.props.date, { format: "DDD" });
    }

    /** @returns {Array<{ title: string, start: Object, end: Object, records: Object[] }>} */
    computeRecordGroups() {
        const recordGroups = this.groupRecords();
        return this.getSortedRecordGroups(recordGroups);
    }
    /**
     * @returns {Array<{ title: string, start: Object, end: Object, records: Object[] }>}
     */
    groupRecords() {
        const recordGroups = {};
        for (const record of this.props.records) {
            const start = record.start;
            const end = record.end;

            const duration = end.diff(start, "days").days;
            const modifiedRecord = Object.create(record);
            modifiedRecord.startHour =
                !record.isAllDay && duration < 1 ? start.toFormat("HH:mm") : "";

            const formattedDate = getFormattedDateSpan(start, end);
            if (!(formattedDate in recordGroups)) {
                recordGroups[formattedDate] = {
                    title: formattedDate,
                    start,
                    end,
                    records: [],
                };
            }
            recordGroups[formattedDate].records.push(modifiedRecord);
        }
        return Object.values(recordGroups);
    }
    /**
     * @param {{ colorIndex: number | string }} record
     * @returns {string}
     */
    getRecordClass(record) {
        const { colorIndex } = record;
        const color = getColor(colorIndex);
        if (color && typeof color === "number") {
            return `o_calendar_color_${color}`;
        }
        return "";
    }
    /**
     * @param {{ colorIndex: number | string }} record
     * @returns {string}
     */
    getRecordStyle(record) {
        const { colorIndex } = record;
        const color = getColor(colorIndex);
        if (color && typeof color === "string") {
            return `background-color: ${color};`;
        }
        return "";
    }
    /**
     * @param {Array<{ title: string, start: Object, end: Object, records: Object[] }>} recordGroups
     * @returns {Array<{ title: string, start: Object, end: Object, records: Object[] }>}
     */
    getSortedRecordGroups(recordGroups) {
        return recordGroups.sort((a, b) => {
            const aSameDay = a.start.hasSame(a.end, "days");
            const bSameDay = b.start.hasSame(b.end, "days");
            if (aSameDay !== bSameDay) {
                return aSameDay ? -1 : 1;
            }
            const startDiff = a.start.toMillis() - b.start.toMillis();
            return startDiff || a.end.toMillis() - b.end.toMillis();
        });
    }

    onCreateButtonClick() {
        this.props.createRecord({
            start: this.props.date,
            isAllDay: true,
        });
        this.props.close();
    }
    /**
     * @param {Object} record
     */
    onRecordClick(record) {
        this.props.editRecord(record);
        this.props.close();
    }
}
