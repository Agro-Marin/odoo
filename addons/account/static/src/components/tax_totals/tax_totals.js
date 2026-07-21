/** @odoo-module native */
import {
    Component,
    onPatched,
    onWillRender,
    onWillUpdateProps,
    toRaw,
    useRef,
    useState,
} from "@odoo/owl";
import { registry } from "@web/core/registry";
import { formatFloat } from "@web/core/utils/format/numbers";
import { formatMonetary } from "@web/fields/formatters";
import { useNumpadDecimal } from "@web/fields/numpad_decimal_hook";
import { parseFloat } from "@web/fields/parsers";
import { standardFieldProps } from "@web/fields/standard_field_props";

/**
 A line of some TaxTotalsComponent, giving the values of a tax group.
 **/
class TaxGroupComponent extends Component {
    static props = {
        totals: { optional: true },
        subtotal: { optional: true },
        taxGroup: { optional: true },
        onChangeTaxGroup: { optional: true },
        isReadonly: Boolean,
    };
    static template = "account.TaxGroupComponent";

    setup() {
        this.inputTax = useRef("taxValueInput");
        this.state = useState({ value: "readonly" });
        onPatched(() => {
            if (this.state.value === "edit") {
                const { taxGroup } = this.props;
                const newVal = formatFloat(taxGroup.tax_amount_currency, {
                    digits: this.props.totals.currency_pd,
                });
                this.inputTax.el.value = newVal;
                this.inputTax.el.focus();
            }
        });
        onWillUpdateProps(() => {
            this.setState("readonly");
        });
        useNumpadDecimal();
    }

    formatMonetary(value) {
        return formatMonetary(value, { currencyId: this.props.totals.currency_id });
    }

    /**
     * Sets the display state: "readonly", "edit" (html input) or "disable"
     * (disabled html input). Any other value falls back to "readonly".
     *
     * @param {String} value
     */
    setState(value) {
        if (["readonly", "edit", "disable"].includes(value)) {
            this.state.value = value;
        } else {
            this.state.value = "readonly";
        }
    }

    /**
     * Applies the tax amount typed in the input: parses it, adds the delta to
     * the tax group, its subtotal and the totals, then notifies the parent.
     * The input is disabled meanwhile. Ignored if the new value is unchanged
     * or 0.
     */
    _onChangeTaxValue() {
        this.setState("disable");
        const oldValue = this.props.taxGroup.tax_amount_currency;
        let newValue;
        try {
            newValue = parseFloat(this.inputTax.el.value);
        } catch {
            this.inputTax.el.value = oldValue;
            this.setState("edit");
            return;
        }
        if (newValue === oldValue || newValue === 0) {
            this.setState("readonly");
            return;
        }
        const deltaValue = newValue - oldValue;
        this.props.taxGroup.tax_amount_currency += deltaValue;
        this.props.subtotal.tax_amount_currency += deltaValue;
        this.props.totals.tax_amount_currency += deltaValue;
        this.props.totals.total_amount_currency += deltaValue;

        this.props.onChangeTaxGroup({
            oldValue,
            newValue: newValue,
            taxGroupId: this.props.taxGroup.id,
        });
    }
}

/**
 Widget used to display tax totals by tax groups for invoices, PO and SO,
 and possibly allowing editing them.
 **/
export class TaxTotalsComponent extends Component {
    static template = "account.TaxTotalsField";
    static components = { TaxGroupComponent };
    static props = {
        ...standardFieldProps,
    };

    setup() {
        this.totals = {};
        this._rawTotals = undefined;
        // onWillRender fires before the first render, so no eager formatData here.
        onWillRender(() => this.formatData(this.props));
    }

    get readonly() {
        return this.props.readonly;
    }

    formatMonetary(value) {
        return formatMonetary(value, { currencyId: this.totals.currency_id });
    }

    /**
     * Handler given to TaxGroupComponent: writes the locally patched totals
     * back to the record when a tax group amount changed.
     */
    _onChangeTaxValueByTaxGroup({ oldValue, newValue }) {
        if (oldValue === newValue) {
            return;
        }
        // Server-derived key: drop it before persisting so it is never written back.
        delete this.totals.cash_rounding_base_amount_currency;
        this.props.record.update({ [this.props.name]: this.totals });
    }

    formatData(props) {
        const raw = toRaw(props.record.data[this.props.name]);
        // Only re-clone when the underlying field object changed identity; otherwise
        // keep the existing clone (avoids a full deep-clone on every re-render).
        if (raw === this._rawTotals) {
            return;
        }
        this._rawTotals = raw;
        if (!raw) {
            return;
        }
        this.totals = JSON.parse(JSON.stringify(raw));
    }
}

export const taxTotalsComponent = {
    component: TaxTotalsComponent,
};

registry.category("fields").add("account-tax-totals-field", taxTotalsComponent);
