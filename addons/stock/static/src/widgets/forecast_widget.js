/** @odoo-module native */
import { FloatField, floatField } from "@web/fields/basic/float/float_field";
import { formatDate } from "@web/core/l10n/dates";
import { formatFloat } from "@web/fields/formatters";
import { registry } from "@web/core/registry";
import { useService } from "@web/core/utils/hooks";

export class ForecastWidgetField extends FloatField {
    static template = "stock.ForecastWidget";
    // NB: intentionally does not call super.setup() — this widget reuses
    // FloatField only for its field descriptor/formatting, not the numeric input
    // the base wires up (the template is a custom badge with no input ref).
    setup() {
        this.actionService = useService("action");
        this.orm = useService("orm");
    }

    // Derived values are getters (not setup-time snapshots) so the badge stays
    // correct when the move's fields change in place in an editable list.
    get resId() {
        return this.props.record.resId;
    }

    get forecastExpectedDate() {
        const { data, fields } = this.props.record;
        return formatDate(data.date_planned_forecast, fields.date_planned_forecast);
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
        const options = { digits: fields.forecast_availability.digits, thousandsSep: "", decimalPoint: "." };
        return (
            parseFloat(formatFloat(data.forecast_availability, options)) >=
            parseFloat(formatFloat(data.product_qty, options))
        );
    }

    get state() {
        return this.props.record.data.state;
    }

    //--------------------------------------------------------------------------
    // Handlers
    //--------------------------------------------------------------------------

    /**
     * Opens the Forecast Report for the `stock.move` product.
     */
    async _openReport(ev) {
        ev.preventDefault();
        ev.stopPropagation();
        if (!this.resId || !this.props.record.data.is_storable) {
            return;
        }
        const action = await this.orm.call("stock.move", "action_product_forecast_report", [
            this.resId,
        ]);
        this.actionService.doAction(action);
    }

    get decoration() {
        if (!this.forecastExpectedDate && this.willBeFulfilled){
            return "text-bg-success"
        } else if (this.forecastExpectedDate && this.willBeFulfilled){
            return this.forecastIsLate ? 'text-bg-danger' : 'text-bg-warning'
        } else {
            return 'text-bg-danger'
        }

    }
}

export const forecastWidgetField = {
    ...floatField,
    component: ForecastWidgetField,
};

registry.category("fields").add("forecast_widget", forecastWidgetField);
