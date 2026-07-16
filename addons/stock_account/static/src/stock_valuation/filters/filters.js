/** @odoo-module native */
import { Component, useRef } from "@odoo/owl";
import { useDateTimePicker } from "@web/components/datetime/datetime_picker_hook";
import { Dropdown } from "@web/components/dropdown/dropdown";
import { formatDate } from "@web/core/l10n/dates";

export class StockValuationReportFilters extends Component {
    static template = "stock_account.StockValuationReport.Filters";
    static components = {
        Dropdown,
    };
    static props = {};

    setup() {
        this.dateFilterRef = useRef("filterDate");
        const getPickerProps = () => {
            const pickerProps = {
                value: this.env.controller.state.date,
                type: "date",
            };
            return pickerProps;
        };
        this.dateTimePicker = useDateTimePicker({
            target: "filterDate",
            get pickerProps() {
                return getPickerProps();
            },
            onApply: (newDate) => {
                if (newDate) {
                    this.env.controller.setDate(newDate);
                    this.render();
                }
            },
        });
    }

    onDateClick() {
        this.dateTimePicker.open();
    }

    get date() {
        return formatDate(this.env.controller.state.date);
    }
}
