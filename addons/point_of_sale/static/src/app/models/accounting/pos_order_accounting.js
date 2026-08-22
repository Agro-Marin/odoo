/** @odoo-module native */
import { accountTaxHelpers } from "@account/helpers/account_tax";
import { formatCurrency } from "@web/core/currency";

import { logPosMessage } from "../../utils/pretty_console_log.js";
import { Base } from "../related_models/index.js";
const CONSOLE_COLOR = "#4EFF4D";

export class PosOrderAccounting extends Base {
    static accountingFields = new Set([
        "pricelist_id",
        "fiscal_position_id",
        "is_refund",
    ]);

    setup(vals) {
        super.setup(vals);
    }

    triggerRecomputeAllPrices() {}

    get currencyDisplayPrice() {
        return formatCurrency(this.displayPrice, this.currency.id);
    }

    get currencyDisplayPriceIncl() {
        return formatCurrency(this.priceIncl, this.currency.id);
    }

    get currencyDisplayPriceExcl() {
        return formatCurrency(this.priceExcl, this.currency.id);
    }

    get currencyAmountTaxes() {
        return formatCurrency(this.amountTaxes, this.currency.id);
    }

    get displayPrice() {
        return this.config.iface_tax_included === "total"
            ? this.currency.round(this.priceIncl)
            : this.currency.round(this.priceExcl);
    }

    get remainingDue() {
        const isNegative = this.totalDue < 0;
        const total = this.totalDue;
        const remaining = total - this.amountPaid;

        if ((isNegative && remaining >= 0) || (!isNegative && remaining <= 0)) {
            return 0;
        }

        const amount =
            this.orderIsRounded &&
            this.config.rounding_method.asymmetricRound(
                isNegative ? -remaining : remaining,
            ) === 0
                ? 0
                : Math.abs(remaining);
        return isNegative ? this.currency.round(-amount) : this.currency.round(amount);
    }
    get change() {
        const isNegative = this.totalDue < 0;
        const roundingSanatizer = this.orderIsRounded ? this.appliedRounding : 0;
        const remaining = this.totalDue - this.amountPaid;

        if ((isNegative && remaining <= 0) || (!isNegative && remaining >= 0)) {
            return 0;
        }

        const total =
            Math.abs(this.priceIncl) -
            Math.abs(this.amountPaid) +
            (isNegative ? -roundingSanatizer : roundingSanatizer);

        const amount = isNegative
            ? -this.currency.round(total)
            : this.currency.round(total);
        return this.shouldRoundChange
            ? this.config.rounding_method.asymmetricRound(amount)
            : amount;
    }
    get shouldRoundChange() {
        return this.orderIsRounded;
    }
    get orderIsRounded() {
        const cashPm = this.payment_ids.some((p) => p.payment_method_id.is_cash_count);
        return this.config.hasGlobalRounding || (cashPm && this.config.hasCashRounding);
    }
    get appliedRounding() {
        const total = this.prices.taxDetails.total_amount_no_rounding;
        const isNegative = this.amountPaid > total;
        const remaining = total - this.amountPaid;
        const amount =
            this.orderIsRounded &&
            this.config.rounding_method.asymmetricRound(
                total < 0 ? -remaining : remaining,
            ) === 0
                ? Math.abs(remaining)
                : 0;
        return isNegative ? this.currency.round(amount) : this.currency.round(-amount);
    }

    get prices() {
        return this._constructPriceData();
    }
    get unitPrices() {
        return this._constructPriceData({ baseLineOpts: { quantity: 1 } });
    }
    get priceIncl() {
        return this.prices.taxDetails.total_amount_no_rounding;
    }
    get priceExcl() {
        return this.prices.taxDetails.base_amount;
    }
    get totalDue() {
        return this.config.hasCashRounding
            ? this.currency.round(this.prices.taxDetails.total_amount_no_rounding)
            : this.currency.round(this.prices.taxDetails.total_amount);
    }
    get amountTaxes() {
        return this.prices.taxDetails.tax_amount_currency;
    }
    get orderHasZeroRemaining() {
        return this.currency.isZero(this.remainingDue);
    }
    get amountPaid() {
        return this.currency.round(
            this.payment_ids.reduce(function (sum, paymentLine) {
                if (paymentLine.isDone() && !paymentLine.is_change) {
                    sum += paymentLine.getAmount();
                }
                return sum;
            }, 0),
        );
    }
    get orderSign() {
        return this.isRefund ? -1 : 1;
    }

    shouldRound(paymentMethod) {
        return paymentMethod.is_cash_count && this.config.hasCashRounding;
    }

    getDefaultAmountDueToPayIn(paymentMethod) {
        const amount = this.shouldRound(paymentMethod)
            ? this.config.rounding_method.round(this.remainingDue)
            : this.remainingDue;
        return amount || this.change;
    }

    setOrderPrices() {
        this.amount_paid = this.amountPaid;
        this.amount_tax = this.amountTaxes;
        this.amount_total = this.currency.round(this.totalDue);
        this.amount_return = this.change;
        this.lines.forEach((line) => {
            line.price_subtotal = line.priceExcl;
            line.price_subtotal_incl = line.priceIncl;
        });
    }
    getPriceWithOptions(opts = {}) {
        return this._constructPriceData(opts);
    }

    /**
     * @private Compute
     */
    _constructPriceData(opts = {}) {
        const data = this._computeAllPrices(opts);
        const lines = opts.lines || this.lines;
        const noDiscount = lines.some((l) => l.getDiscount() > 0)
            ? this._computeAllPrices({
                  ...opts,
                  baseLineOpts: { ...(opts.baseLineOpts || {}), discount: 0.0 },
              })
            : data;
        const currency = this.currency;

        for (const key of Object.keys(data.baseLineByLineUuids)) {
            const ndData = noDiscount.baseLineByLineUuids[key].tax_details;
            const dData = data.baseLineByLineUuids[key].tax_details;

            Object.assign(data.baseLineByLineUuids[key].tax_details, {
                discount_amount: currency.round(
                    (this.config.iface_tax_included === "total"
                        ? ndData.total_included - dData.total_included
                        : ndData.total_excluded - dData.total_excluded) *
                        this.orderSign,
                ),
                no_discount_total_excluded: ndData.total_excluded,
                no_discount_total_included: ndData.total_included,
                no_discount_total_included_currency: ndData.total_included_currency,
                no_discount_total_excluded_currency: ndData.total_excluded_currency,
                no_discount_taxes_data: ndData.taxes_data,
                no_discount_delta_total_excluded: ndData.delta_total_excluded,
                no_discount_delta_total_included: ndData.delta_total_included,
            });
        }

        if (odoo.debug) {
            logPosMessage(
                "Accounting",
                "_constructPriceData",
                "Recompute allPrices",
                CONSOLE_COLOR,
                [data],
            );
        }
        return data;
    }

    /**
     * @private Compute
     */
    _computeAllPrices(opts = {}) {
        const currency = this.currency;
        const lines = opts.lines || this.lines;
        const documentSign = this.isRefund ? -1 : 1;
        const company = this.company;
        const baseLines = lines.map((l) =>
            l.getBaseLine({
                quantity: l.qty,
                price_unit: l.price_unit,
                ...(opts.baseLineOpts || {}),
            }),
        );

        accountTaxHelpers.add_tax_details_in_base_lines(baseLines, company);
        accountTaxHelpers.round_base_lines_tax_details(baseLines, company);

        const cashRounding = this.config.hasGlobalRounding
            ? this.config.rounding_method
            : null;
        const data = accountTaxHelpers.get_tax_totals_summary(
            baseLines,
            currency,
            company,
            {
                cash_rounding: cashRounding,
            },
        );
        const total =
            data.total_amount_currency -
            (data.cash_rounding_base_amount_currency || 0.0);

        data.order_sign = documentSign;
        data.total_amount_no_rounding = total;

        const baseLineByLineUuids = baseLines.reduce((acc, line) => {
            acc[line.record.uuid] = line;
            return acc;
        }, {});

        return {
            taxDetails: data,
            baseLines: baseLines,
            baseLineByLineUuids: baseLineByLineUuids,
        };
    }
}
