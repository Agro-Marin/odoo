// @ts-check
/** @odoo-module native */

import { Component, useExternalListener } from "@odoo/owl";
import { is24HourFormat } from "@web/core/l10n/time";
import { evaluateBooleanExpr } from "@web/core/py_js/py";
import { registry } from "@web/core/registry";
import { _t } from "@web/core/translation";
import { Field } from "@web/fields/field";
import { Record } from "@web/model/record";
import { Dialog } from "@web/ui/dialog/dialog";
import { getFormattedDateSpan } from "@web/views/calendar/calendar_utils";

/**
 * @param {string} str
 * @returns {string}
 */
function luxonLiteral(str) {
    return String(str).replaceAll("'", "''");
}

export class CalendarCommonPopover extends Component {
    static template = "web.CalendarCommonPopover";
    static subTemplates = {
        popover: "web.CalendarCommonPopover.popover",
        body: "web.CalendarCommonPopover.body",
        footer: "web.CalendarCommonPopover.footer",
    };
    static components = {
        Dialog,
        Field,
        Record,
    };
    static props = {
        close: Function,
        record: Object,
        model: Object,
        createRecord: Function,
        deleteRecord: Function,
        editRecord: Function,
    };

    setup() {
        this.time = null;
        this.timeDuration = null;
        this.date = null;
        this.dateDuration = null;

        useExternalListener(
            window,
            "pointerdown",
            (e) => {
                const target = /** @type {HTMLElement} */ (e.target);
                const onCalendar = target.closest(".o_calendar_widget, .fc-popover");
                const onSourceEvent = target.closest(
                    `.fc-event[data-event-id="${this.props.record.id}"]`,
                );
                if (onCalendar && !onSourceEvent) {
                    e.preventDefault();
                }
            },
            { capture: true },
        );

        this.computeDateTimeAndDuration();
    }

    get activeFields() {
        return this.props.model.activeFields;
    }
    get isEventEditable() {
        return this.props.model.canEdit;
    }
    get isEventDeletable() {
        return this.props.model.canDelete;
    }
    get isEventViewable() {
        return true;
    }
    get hasFooter() {
        return this.isEventEditable || this.isEventDeletable || this.isEventViewable;
    }

    /**
     * @param {{ [key: string]: any }} fieldNode
     * @param {{ [key: string]: any }} record
     * @returns {boolean}
     */
    isInvisible(fieldNode, record) {
        return evaluateBooleanExpr(
            fieldNode.invisible,
            record.evalContextWithVirtualIds,
        );
    }

    /**
     * @param {string} fieldName
     * @param {{ [key: string]: any }} record
     * @returns {string}
     */
    getFormattedValue(fieldName, record) {
        const fieldInfo = this.props.model.popoverFieldNodes[fieldName];
        const field = this.props.model.fields[fieldName];
        let format;
        const formattersRegistry = registry.category("formatters");
        if (fieldInfo.widget && formattersRegistry.contains(fieldInfo.widget)) {
            format = formattersRegistry.get(fieldInfo.widget);
        } else {
            format = formattersRegistry.get(field.type);
        }
        return format(record.data[fieldName]);
    }

    computeDateTimeAndDuration() {
        const record = this.props.record;
        const { start, end } = record;
        const isSameDay = start.hasSame(end, "day");

        if (!record.isTimeHidden && !record.isAllDay && isSameDay) {
            const timeFormat = is24HourFormat() ? "HH:mm" : "hh:mm a";
            this.time = `${start.toFormat(timeFormat)} - ${end.toFormat(timeFormat)}`;

            const duration = end.diff(start, ["hours", "minutes"]);
            const formatParts = [];
            if (duration.hours > 0) {
                const hourString = duration.hours === 1 ? _t("hour") : _t("hours");
                formatParts.push(`h '${luxonLiteral(hourString)}'`);
            }
            if (duration.minutes > 0) {
                const minuteStr = duration.minutes === 1 ? _t("minute") : _t("minutes");
                formatParts.push(`m '${luxonLiteral(minuteStr)}'`);
            }
            this.timeDuration = formatParts.length
                ? duration.toFormat(formatParts.join(", "))
                : _t("0 minutes");
        }

        if (!this.props.model.isDateHidden) {
            this.date = getFormattedDateSpan(start, end);

            if (record.isAllDay) {
                if (isSameDay) {
                    this.dateDuration = _t("All day");
                } else {
                    const duration = end.plus({ day: 1 }).diff(start, "days");
                    this.dateDuration = duration.toFormat(
                        `d '${luxonLiteral(_t("days"))}'`,
                    );
                }
            }
        }
    }

    onEditEvent() {
        this.props.editRecord(this.props.record);
        this.props.close();
    }
    onDeleteEvent() {
        this.props.deleteRecord(this.props.record);
        this.props.close();
    }
}
