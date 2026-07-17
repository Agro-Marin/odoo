/** @odoo-module native */
import { formatDate } from "@web/core/l10n/dates";
import { registry } from "@web/core/registry";
import { useService } from "@web/core/utils/hooks";
import { FloatField, floatField } from "@web/fields/basic/float/float_field";
import { formatFloat } from "@web/fields/formatters";

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
        // formatDate's second argument is an options object ({ format }); the
        // localization default date format is what we want here.
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
        const action = await this.orm.call(
            "stock.move",
            "action_product_forecast_report",
            [this.resId],
        );
        this.actionService.doAction(action);
    }

    // Single source of truth for the badge's tri-state, consumed by both the
    // color (`decoration`) and the label (template) so they can never disagree.
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
