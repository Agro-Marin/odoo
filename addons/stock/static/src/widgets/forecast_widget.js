/** @odoo-module native */
import { formatFloat } from "@web/core/formatters";
import { formatDate } from "@web/core/l10n/dates";
import { registry } from "@web/core/registry";
import { useService } from "@web/core/utils/hooks";
import { FloatField, floatField } from "@web/fields/basic/float/float_field";

export class ForecastWidgetField extends FloatField {
    static template = "stock.ForecastWidget";
    setup() {
        this.actionService = useService("action");
        this.orm = useService("orm");
    }

    get resId() {
        return this.props.record.resId;
    }

    get forecastExpectedDate() {
        return formatDate(this.props.record.data.date_planned_forecast);
    }

    get forecastIsLate() {
        const { data } = this.props.record;
        return (
            data.date_planned_forecast &&
            data.date_deadline &&
            data.date_planned_forecast > data.date_deadline
        );
    }

    get willBeFulfilled() {
        const { data, fields } = this.props.record;
        const options = {
            digits: fields.forecast_availability.digits,
            thousandsSep: "",
            decimalPoint: ".",
        };
        return (
            parseFloat(formatFloat(data.forecast_availability, options)) >=
            parseFloat(formatFloat(data.product_qty, options))
        );
    }

    get state() {
        return this.props.record.data.state;
    }

    async _openReport(ev) {
        ev.preventDefault();
        ev.stopPropagation();
        if (!this.resId || !this.props.record.data.is_storable) {
            return;
        }
        const action = await this.orm.call(
            "stock.move",
            "action_product_forecast_report",
            [this.resId],
        );
        this.actionService.doAction(action);
    }

    get status() {
        if (this.willBeFulfilled) {
            return this.forecastExpectedDate ? "expected" : "available";
        }
        return "unavailable";
    }

    get decoration() {
        switch (this.status) {
            case "available":
                return "text-bg-success";
            case "expected":
                return this.forecastIsLate ? "text-bg-danger" : "text-bg-warning";
            default:
                return "text-bg-danger";
        }
    }
}

export const forecastWidgetField = {
    ...floatField,
    component: ForecastWidgetField,
};

registry.category("fields").add("forecast_widget", forecastWidgetField);
