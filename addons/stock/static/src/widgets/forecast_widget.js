/** @odoo-module native */
import { Component } from "@odoo/owl";
import { formatDate } from "@web/core/l10n/dates";
import { registry } from "@web/core/registry";
import { roundDecimals } from "@web/core/utils/format/numbers";
import { useService } from "@web/core/utils/hooks";
import { floatField } from "@web/fields/basic/float/float_field";
import { standardFieldProps } from "@web/fields/standard_field_props";

export class ForecastWidgetField extends Component {
    static template = "stock.ForecastWidget";
    static props = { ...standardFieldProps };

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
        const decimals = fields.forecast_availability.digits?.[1] ?? 2;
        return (
            roundDecimals(data.forecast_availability - data.product_qty, decimals) >= 0
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
    fieldDependencies: [
        { name: "product_qty", type: "float" },
        { name: "date_planned_forecast", type: "datetime" },
        { name: "date_deadline", type: "datetime" },
        { name: "is_storable", type: "boolean" },
        { name: "state", type: "selection" },
    ],
    extractProps: () => ({}),
};

registry.category("fields").add("forecast_widget", forecastWidgetField);
