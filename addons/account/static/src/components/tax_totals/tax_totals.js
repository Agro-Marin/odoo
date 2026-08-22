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
import { formatMonetary } from "@web/core/formatters";
import { parseFloat } from "@web/core/parsers";
import { registry } from "@web/core/registry";
import { formatFloat } from "@web/core/utils/format/numbers";
import { useNumpadDecimal } from "@web/fields/numpad_decimal_hook";
import { standardFieldProps } from "@web/fields/standard_field_props";

class TaxGroupComponent extends Component {
    static props = {
        taxGroup: { type: Object },
        subtotal: { type: Object },
        currencyId: { type: Number, optional: true },
        currencyPd: { type: Number, optional: true },
        onChangeTaxGroup: { type: Function },
        isReadonly: Boolean,
    };
    static template = "account.TaxGroupComponent";

    setup() {
        this.inputTax = useRef("taxValueInput");
        this.state = useState({ value: "readonly" });
        onPatched(() => {
            if (this.state.value === "edit") {
                this.inputTax.el.value = this.formatAmount(
                    this.props.taxGroup.tax_amount_currency,
                );
                this.inputTax.el.focus();
            }
        });
        onWillUpdateProps(() => {
            this.setState("readonly");
        });
        useNumpadDecimal();
    }

    formatMonetary(value) {
        return formatMonetary(value, { currencyId: this.props.currencyId });
    }

    /** @returns {string} */
    formatAmount(value) {
        return formatFloat(value, { digits: this.props.currencyPd });
    }

    /**
     * @param {String} value
     */
    setState(value) {
        if (["readonly", "edit", "disable"].includes(value)) {
            this.state.value = value;
        } else {
            this.state.value = "readonly";
        }
    }

    onChangeTaxValue() {
        this.setState("disable");
        const oldValue = this.props.taxGroup.tax_amount_currency;
        let newValue;
        try {
            newValue = parseFloat(this.inputTax.el.value);
        } catch {
            this.inputTax.el.value = this.formatAmount(oldValue);
            this.setState("edit");
            return;
        }
        if (newValue === oldValue) {
            this.setState("readonly");
            return;
        }
        this.props.onChangeTaxGroup({
            subtotal: this.props.subtotal,
            taxGroup: this.props.taxGroup,
            amount: newValue,
        });
    }
}

export class TaxTotalsComponent extends Component {
    static template = "account.TaxTotalsField";
    static components = { TaxGroupComponent };
    static props = {
        ...standardFieldProps,
    };

    setup() {
        this.totals = {};
        this._rawTotals = undefined;
        onWillRender(() => this.formatData(this.props));
    }

    get readonly() {
        return this.props.readonly;
    }

    formatMonetary(value) {
        return formatMonetary(value, { currencyId: this.totals.currency_id });
    }

    /**
     * @param {{subtotal: Object, taxGroup: Object, amount: number}} change
     */
    onTaxGroupAmountChanged({ subtotal, taxGroup, amount }) {
        const delta = amount - taxGroup.tax_amount_currency;
        if (!delta) {
            return;
        }
        taxGroup.tax_amount_currency += delta;
        subtotal.tax_amount_currency += delta;
        this.totals.tax_amount_currency += delta;
        this.totals.total_amount_currency += delta;

        const changes = JSON.parse(JSON.stringify(this.totals));
        delete changes.cash_rounding_base_amount_currency;
        this.props.record.update({ [this.props.name]: changes });
    }

    formatData(props) {
        const raw = toRaw(props.record.data[this.props.name]);
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
