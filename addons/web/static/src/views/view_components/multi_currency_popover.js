// @ts-check
/** @odoo-module native */

/** @module @web/views/view_components/multi_currency_popover */

import {
    Component,
    onWillStart,
    useExternalListener,
    useRef,
    useState,
} from "@odoo/owl";
import { getCurrency, getCurrencyRates } from "@web/core/currency";
import { formatMonetary } from "@web/core/formatters";
import { toLocaleDateString } from "@web/core/l10n/dates";
import { user } from "@web/core/user";

export class MultiCurrencyPopover extends Component {
    static template = "web.MultiCurrencyPopover";
    static props = {
        close: Function,
        currencyIds: Array,
        target: HTMLElement,
        value: Number,
    };

    /** @type {import("@odoo/owl").Ref} */
    rootRef;
    /** @type {{ rates: null }} */
    state;

    setup() {
        this.rootRef = useRef("root");
        this.defaultCurrency = user.activeCompany?.currency_id;
        this.state = useState({ rates: null });
        onWillStart(async () => {
            this.state.rates = await getCurrencyRates();
        });
        useExternalListener(window, "mouseover", (ev) => {
            const popoverEl = this.rootRef.el;
            const target = /** @type {Node} */ (ev.target);
            if (!this.props.target.contains(target) && !popoverEl?.contains(target)) {
                this.props.close();
            }
        });
    }

    /** @returns {Array<Object>} */
    get currencies() {
        return this.props.currencyIds.reduce((currencies, currencyId) => {
            const rateInfo = this.state.rates[currencyId];
            if (currencyId && currencyId !== this.defaultCurrency && rateInfo) {
                currencies.push({
                    ...getCurrency(currencyId),
                    id: currencyId,
                    toCompanyRate: rateInfo.toCompanyRate,
                    date: toLocaleDateString(rateInfo.date),
                    // props.value is already in the company currency
                    value: this.props.value / rateInfo.toCompanyRate,
                });
            }
            return currencies;
        }, []);
    }

    /**
     * @param {number} value
     * @param {number} currencyId
     * @returns {string}
     */
    formatedValue(value, currencyId) {
        return formatMonetary(value, { currencyId });
    }
}
