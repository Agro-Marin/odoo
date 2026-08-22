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

/**
 A line of some TaxTotalsComponent, giving the values of a tax group.
 **/
class TaxGroupComponent extends Component {
    static props = {
        // Its own row, and the subtotal that row belongs to. Both are passed
        // back untouched when the amount changes: the owner of the totals tree
        // applies the change, this component only reports it.
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

    /** @returns {string} the amount as the input shows it while editing */
    formatAmount(value) {
        return formatFloat(value, { digits: this.props.currencyPd });
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
     * Report the amount typed in the input to the owner of the totals. The
     * input is disabled meanwhile, and an unparseable value is put back the way
     * it was displayed rather than as a raw float.
     */
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
     * Apply a tax group's new amount to the totals this component owns, then
     * persist them.
     *
     * The arithmetic lives here because the tree does: a tax group's amount is
     * carried by its group, its subtotal and the grand total at once, and a
     * child reaching up to update all three left the data flowing through a
     * shared mutable object rather than through props and a callback.
     *
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
        // Server-derived: drop it from what is written, but not from what is on
        // screen — deleting it in place made the Rounding row vanish until the
        // server answered.
        delete changes.cash_rounding_base_amount_currency;
        this.props.record.update({ [this.props.name]: changes });
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
