// @ts-check
/** @odoo-module native */

/** @module @web/views/view_components/multi_currency_popover - Popover showing a monetary value converted into each active company currency */

import {
    Component,
    onWillStart,
    useExternalListener,
    useRef,
    useState,
} from "@odoo/owl";
import { toLocaleDateString } from "@web/core/l10n/dates";
import { formatMonetary } from "@web/fields/formatters";
import { getCurrency, getCurrencyRates } from "@web/services/currency";
import { user } from "@web/services/user";

/** Popover showing a monetary value converted into each of the company's active currencies. */
export class MultiCurrencyPopover extends Component {
    static template = "web.MultiCurrencyPopover";
    static props = {
        close: Function,
        currencyIds: Array,
        target: HTMLElement,
        value: Number,
    };

    setup() {
        this.rootRef = useRef("root");
        this.defaultCurrency = user.activeCompany?.currency_id;
        this.state = useState({ rates: null });
        onWillStart(async () => {
            this.state.rates = await getCurrencyRates();
        });
        useExternalListener(window, "mouseover", (ev) => {
            // Close only when the pointer leaves BOTH anchor and popover; a
            // naive `ev.target !== target` check fired as soon as the
            // pointer entered the popover or any child of the anchor.
            const popoverEl = this.rootRef.el;
            if (
                !this.props.target.contains(ev.target) &&
                !popoverEl?.contains(ev.target)
            ) {
                this.props.close();
            }
        });
    }

    /** @returns {Array<Object>} non-default currencies with their rates and converted values */
    get currencies() {
        return this.props.currencyIds.reduce((currencies, currencyId) => {
            const rateInfo = this.state.rates[currencyId];
            if (currencyId && currencyId !== this.defaultCurrency && rateInfo) {
                currencies.push({
                    ...getCurrency(currencyId),
                    id: currencyId,
                    rate: rateInfo.rate,
                    date: toLocaleDateString(rateInfo.date),
                    value: this.props.value / rateInfo.rate,
                });
            }
            return currencies;
        }, []);
    }

    /**
     * @param {number} value
     * @param {number} currencyId
     * @returns {string} formatted monetary string
     */
    formatedValue(value, currencyId) {
        return formatMonetary(value, { currencyId });
    }
}
