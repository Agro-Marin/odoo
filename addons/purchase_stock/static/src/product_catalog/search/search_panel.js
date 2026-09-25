/** @odoo-module native */
import { useState } from "@odoo/owl";
import { useProductCatalogContext } from "@product/product_catalog/product_catalog_context";
import { ProductCatalogSearchPanel } from "@product/product_catalog/search/search_panel";
import { formatMonetary } from "@web/core/formatters";
import { _t } from "@web/core/translation";
import { clamp } from "@web/core/utils/format/numbers";
import { useService } from "@web/core/utils/hooks";
import { useSearchModel } from "@web/search/search_model";

import { TimePeriodSelectionField } from "./time_period_selection_fields.js";

export class PurchaseSuggestCatalogSearchPanel extends ProductCatalogSearchPanel {
    static template = "purchase_stock.ProductCatalogSearchPanel";
    static components = { TimePeriodSelectionField };
    static basedOnOptions = [
        ["actual_demand", _t("Forecasted")],
        ["one_week", _t("Last 7 days")],
        ["30_days", _t("Last 30 days")],
        ["three_months", _t("Last 3 months")],
        ["one_year", _t("Last 12 months")],
        ["last_year", _t("Same month last year")],
        ["last_year_m_plus_1", _t("Next month last year")],
        ["last_year_m_plus_2", _t("After next month last year")],
        ["last_year_quarter", _t("Last year quarter")],
    ];

    setup() {
        super.setup();
        this.searchModel = useSearchModel();
        this.ui = useService("ui");
        const catalog = useProductCatalogContext();
        this.suggest = useState(catalog.suggest);
        this.toggleSuggest = catalog.toggleSuggest;
        this.debouncedReloadKanban = catalog.debouncedReloadKanban;
        this.reloadKanban = catalog.reloadKanban;
        this.addAllProducts = catalog.addAllProducts;
        this.displaySuggest = this.suggest.poState === "draft";
        this.tooltipTitle = _t(
            "Get recommendations of products to purchase at %(vendorName)s based on stock on hand, incoming quantities, " +
                "and expected sales volumes.\n\n Set a reference period to estimate sales, and use the percentage " +
                "to take into account seasonality and the increase/decrease of business.",
            { vendorName: this.suggest.vendorName },
        );
    }
    onDaysInput(ev) {
        const value = parseInt(ev.target.value, 10) || 0;
        const boundedVal = clamp(value, 0, 999);
        this.suggest.numberOfDays = boundedVal;
        ev.target.value = boundedVal;
        this.debouncedReloadKanban();
    }
    onPercentFactorInput(ev) {
        const value = parseInt(ev.target.value, 10) || 0;
        const boundedVal = clamp(value, 0, 999);
        this.suggest.percentFactor = boundedVal;
        ev.target.value = boundedVal;
        this.debouncedReloadKanban();
    }
    get estimatedSuggestPrice() {
        const { currencyId, digits } = this.suggest;
        return formatMonetary(this.suggest.totalEstimatedPrice, { currencyId, digits });
    }
    get timePeriodProps() {
        return {
            name: "based_on",
            required: true,
            record: {
                data: { based_on: this.suggest.basedOn },
                fields: { based_on: { selection: this.constructor.basedOnOptions } },
            },
            onChange: (val) => {
                this.suggest.basedOn = val;
                this.reloadKanban();
            },
        };
    }

    selectAllOnClick(ev) {
        const el = ev.currentTarget;
        if (el.disabled || el.readOnly) {
            return;
        }
        ev.preventDefault();
        el.focus();
        el.select();
    }
}
