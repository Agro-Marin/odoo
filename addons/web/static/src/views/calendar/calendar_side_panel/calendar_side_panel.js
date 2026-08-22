// @ts-check
/** @odoo-module native */

import { Component } from "@odoo/owl";
import { DateTimePicker } from "@web/components/datetime/datetime_picker";
import { getStartOfLocalWeek } from "@web/core/l10n/date_utils";
import { CalendarFilterSection } from "@web/views/calendar/calendar_filter_section/calendar_filter_section";

export class CalendarSidePanel extends Component {
    static components = {
        DatePicker: DateTimePicker,
        FilterSection: CalendarFilterSection,
    };
    static template = "web.CalendarSidePanel";
    static props = ["model"];

    /** @returns {Object} */
    get datePickerProps() {
        return {
            type: "date",
            showWeekNumbers: false,
            maxPrecision: "days",
            daysOfWeekFormat: "narrow",
            onSelect: (
                /** @type {import("@web/core/l10n/dates").NullableDateTime} */ date,
            ) => {
                let scale = "week";

                if (this.props.model.date.hasSame(date, "day")) {
                    const scales = ["month", "week", "day"];
                    scale =
                        scales[
                            (scales.indexOf(this.props.model.scale) + 1) % scales.length
                        ];
                } else {
                    const currentWeekStart = getStartOfLocalWeek(this.props.model.date);
                    const pickedWeekStart = getStartOfLocalWeek(date);
                    if (currentWeekStart.hasSame(pickedWeekStart, "day")) {
                        scale = "day";
                    }
                }

                this.props.model.load({ scale, date });
            },
            value: this.props.model.date,
        };
    }
    /** @returns {{ model: Object }} */
    get filterPanelProps() {
        return {
            model: this.props.model,
        };
    }

    /** @returns {boolean} */
    get showDatePicker() {
        return this.props.model.showDatePicker && !this.env.isSmall;
    }
}
