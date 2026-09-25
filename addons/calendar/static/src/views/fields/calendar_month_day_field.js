/** @odoo-module native */
import { registry } from "@web/core/registry";
import { _t } from "@web/core/translation";
import {
    SelectionField,
    selectionField,
} from "@web/fields/selection/selection/selection_field";

export const LAST_DAY_OF_MONTH = -1;

export class CalendarMonthDayField extends SelectionField {
    get options() {
        const days = Array.from({ length: 31 }, (_, index) => [
            index + 1,
            String(index + 1),
        ]);
        return [...days, [LAST_DAY_OF_MONTH, _t("Last day")]];
    }

    get string() {
        return this.options.find(([value]) => value === this.value)?.[1] ?? "";
    }

    onChange(value) {
        if (this.props.readonly || value === null || value === undefined) {
            return;
        }
        this.field.update(value, { save: this.props.autosave });
    }
}

export const calendarMonthDayField = {
    ...selectionField,
    component: CalendarMonthDayField,
    displayName: _t("Day of the month"),
    supportedTypes: ["integer"],
};

registry.category("fields").add("calendar_month_day", calendarMonthDayField);
