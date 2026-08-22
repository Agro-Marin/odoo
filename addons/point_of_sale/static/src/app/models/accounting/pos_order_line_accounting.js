/** @odoo-module native */
import { accountTaxHelpers } from "@account/helpers/account_tax";
import { formatCurrency } from "@web/core/currency";
import { _t } from "@web/core/translation";

import { Base } from "../related_models/index.js";

export class PosOrderlineAccounting extends Base {
    static accountingFields = new Set([
        "order_id",
        "qty",
        "price_unit",
        "discount",
        "tax_ids",
        "price_type",
        "price_extra",
    ]);

    get currencyDisplayPrice() {
        if (this.combo_parent_id) {
            return "";
        }

        if (this.getDiscount() === 100) {
            return _t("Free");
        }

        return formatCurrency(this.displayPrice, this.currency.id);
    }
    get currencyDisplayPriceUnit() {
        return formatCurrency(this.displayPriceUnit, this.currency.id);
    }
    get currencyDisplayPriceUnitExcl() {
        return formatCurrency(this.displayPriceUnitExcl, this.currency.id);
    }

    _comboGlobalTotal({ noDiscount = false } = {}) {
        const opts = { lines: this.combo_line_ids };
        if (noDiscount) {
            opts.baseLineOpts = { discount: 0.0 };
        }
        const details = this.order_id.getPriceWithOptions(opts).taxDetails;
        const raw =
            this.config.iface_tax_included === "total"
                ? details.total_amount_no_rounding
                : details.base_amount;
        return this.currency.round(raw * this.order_id.orderSign);
    }
    get displayPrice() {
        if (this.combo_line_ids.length) {
            return this._comboGlobalTotal();
        }
        return this.config.iface_tax_included === "total"
            ? this.priceIncl
            : this.priceExcl;
    }
    get displayPriceNoDiscount() {
        if (this.combo_line_ids.length) {
            return this._comboGlobalTotal({ noDiscount: true });
        }
        return this.config.iface_tax_included === "total"
            ? this.priceInclNoDiscount
            : this.priceExclNoDiscount;
    }
    get displayPriceUnit() {
        return this.config.iface_tax_included === "total"
            ? this.unitPrices.total_included
            : this.unitPrices.total_excluded;
    }
    get displayPriceUnitExcl() {
        return this.unitPrices.total_excluded;
    }
    get displayPriceUnitNoDiscount() {
        return this.config.iface_tax_included === "total"
            ? this.unitPrices.no_discount_total_included
            : this.unitPrices.no_discount_total_excluded;
    }

    get priceIncl() {
        return this.currency.round(
            this.prices.total_included * this.order_id.orderSign,
        );
    }
    get priceExcl() {
        return this.currency.round(
            this.prices.total_excluded * this.order_id.orderSign,
        );
    }
    get priceInclNoDiscount() {
        return this.currency.round(
            this.prices.no_discount_total_included * this.order_id.orderSign,
        );
    }
    get priceExclNoDiscount() {
        return this.currency.round(
            this.prices.no_discount_total_excluded * this.order_id.orderSign,
        );
    }

    get prices() {
        const data = this.order_id.prices.baseLineByLineUuids[this.uuid];
        return data.tax_details;
    }

    get unitPrices() {
        const data = this.order_id.unitPrices.baseLineByLineUuids[this.uuid];
        return data.tax_details;
    }

    get comboTotalPrice() {
        const childLines = this.getAllLinesInCombo().filter(
            (line) => !line.combo_line_ids.length,
        );
        return childLines.reduce((total, line) => total + line.priceIncl, 0);
    }

    get comboTotalPriceWithoutTax() {
        const childLines = this.getAllLinesInCombo().filter(
            (line) => !line.combo_line_ids.length,
        );
        return childLines.reduce((total, line) => total + line.priceExcl, 0);
    }

    get taxGroupLabels() {
        let taxes_id = this.tax_ids;
        if (this.order_id.fiscal_position_id) {
            taxes_id = this.order_id.fiscal_position_id.getTaxesAfterFiscalPosition(
                this.tax_ids,
            );
        }
        return [
            ...new Set(
                taxes_id
                    ?.map((tax) => tax.tax_group_id.pos_receipt_label)
                    .filter((label) => label),
            ),
        ].join(" ");
    }

    get basePrice() {
        return this.qty * this.price_unit * (1 - this.getDiscount() / 100);
    }

    prepareBaseLineForTaxesComputationExtraValues(customValues = {}) {
        const order = this.order_id;
        const currency = this.config.currency_id;
        const extraValues = { currency_id: currency };
        const product = this.getProduct();
        const productUom = this.getUnit();
        const priceUnit = this.price_unit || 0;
        const discount = this.getDiscount();
        const values = {
            ...extraValues,
            quantity: this.qty,
            price_unit: priceUnit,
            discount: discount,
            tax_ids: this.tax_ids,
            product_id: product,
            product_uom_id: productUom,
            rate: 1.0,
            is_refund: this.qty * priceUnit < 0,
            ...customValues,
        };
        if (order?.fiscal_position_id && product !== this.config.discount_product_id) {
            values.tax_ids = order.fiscal_position_id.getTaxesAfterFiscalPosition(
                values.tax_ids,
            );
        }
        return values;
    }

    getBaseLine(opts = {}) {
        return accountTaxHelpers.prepare_base_line_for_taxes_computation(
            this,
            this.prepareBaseLineForTaxesComputationExtraValues({
                price_unit: this.price_unit,
                quantity: this.getQuantity(),
                tax_ids: this.tax_ids,
                ...opts,
            }),
        );
    }
}
