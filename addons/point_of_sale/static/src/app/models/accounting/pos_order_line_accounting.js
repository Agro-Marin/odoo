/** @odoo-module native */
import { accountTaxHelpers } from "@account/helpers/account_tax";
import { _t } from "@web/core/l10n/translation";
import { formatCurrency } from "@web/services/currency";

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

    /**
     * Display price in the currency format, depending on the tax configuration (included or excluded).
     *
     * All getters in this section are used in XML files, their goal is to be shown in the UI.
     */
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

    /**
     * Display price depending on the tax configuration (included or excluded).
     */
    // A combo parent's shown price is the total of its child lines. Compute it
    // the SAME way the order total is computed — a single GLOBAL tax summary
    // over the combo's child lines (via the order's own price machinery) —
    // instead of summing each child's already-rounded price. Line-by-line
    // rounding accumulated a per-cent drift, so the parent could show e.g.
    // 151.97 while the order charged the globally-rounded 151.98.
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
        return this.currency.round(raw);
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

    /**
     * Return all prices details of an orderlines based on the order prices computation.
     * This is the preferred way to get prices of an orderline since its rounded globally.
     */
    get prices() {
        const data = this.order_id.prices.baseLineByLineUuids[this.uuid];
        return data.tax_details;
    }

    /**
     * Same as "get prices" but the prices are computed as if the quantity was 1.
     */
    get unitPrices() {
        const data = this.order_id.unitPrices.baseLineByLineUuids[this.uuid];
        return data.tax_details;
    }

    get comboTotalPrice() {
        // Line totals, tax-included — deliberately independent of the
        // iface_tax_included display configuration: pos_loyalty uses this pair
        // as "amount with tax"/"amount without tax" for rule thresholds and
        // discount bases.
        const childLines = this.getAllLinesInCombo().filter(
            (line) => !line.combo_line_ids.length,
        );
        return childLines.reduce((total, line) => total + line.priceIncl, 0);
    }

    get comboTotalPriceWithoutTax() {
        // Line totals, tax-excluded. Summing displayPriceUnitExcl here
        // undercounted every combo child with a quantity above 1 (it is a
        // quantity-1 price).
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

    // NB: the delete() override that used to trigger an order price recompute
    // is gone — prices are lazy getters invalidated by the raw x2many
    // mutation itself. (Its `delete(record, opts)` signature also contradicted
    // Base.delete(opts) and only worked because the options object landed in
    // the `record` slot.)

    get basePrice() {
        return this.qty * this.price_unit * (1 - this.getDiscount() / 100);
    }

    /**
     * Prepare extra values for the base line used in taxes computation.
     */
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
            // Recompute taxes based on product and fiscal position.
            values.tax_ids = order.fiscal_position_id.getTaxesAfterFiscalPosition(
                values.tax_ids,
            );
        }
        return values;
    }

    /**
     * Get the base line for taxes computation.
     */
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
