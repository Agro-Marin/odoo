// @ts-check
/** @odoo-module native */

/** @module @web/views/calendar/calendar_side_panel/calendar_side_panel - Side panel with date picker and filter sections for the calendar view */

import { Component } from "@odoo/owl";
import { DateTimePicker } from "@web/components/datetime/datetime_picker";
import { getStartOfLocalWeek } from "@web/core/l10n/date_utils";
import { CalendarFilterSection } from "@web/views/calendar/calendar_filter_section/calendar_filter_section";

/** Side panel with a date picker and filter sections for the calendar view. */
export class CalendarSidePanel extends Component {
    static components = {
        DatePicker: DateTimePicker,
        FilterSection: CalendarFilterSection,
    };
    static template = "web.CalendarSidePanel";
    static props = ["model"];

    /** @returns {Object} props passed to the DateTimePicker component */
    get datePickerProps() {
        return {
            type: "date",
            showWeekNumbers: false,
            maxPrecision: "days",
            daysOfWeekFormat: "narrow",
            onSelect: (date) => {
                let scale = "week";

                if (this.props.model.date.hasSame(date, "day")) {
                    const scales = ["month", "week", "day"];
                    scale =
                        scales[
                            (scales.indexOf(this.props.model.scale) + 1) % scales.length
                        ];
                } else {
                    // Luxon's hasSame(b, "week") assumes Monday-start weeks, so bucket by
                    // the locale's own week start instead: two dates share a week iff
                    // their local week starts fall on the same day.
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
    /** @returns {{ model: Object }} props passed to the CalendarFilterSection */
    get filterPanelProps() {
        return {
            model: this.props.model,
        };
    }

    /** @returns {boolean} whether the date picker should be visible */
    get showDatePicker() {
        return this.props.model.showDatePicker && !this.env.isSmall;
    }
}
