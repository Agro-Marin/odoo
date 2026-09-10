/** @odoo-module native */
import { AccountProductCatalogSearchModel } from "@account/components/product_catalog/search/search_model";
import { reactive, useSubEnv } from "@odoo/owl";

import { getSuggestToggleState } from "../utils.js";

export class PurchaseStockProductCatalogSearchModel extends AccountProductCatalogSearchModel {
    setup() {
        super.setup(...arguments);
        // The total arrives from its own RPC after the kanban has reloaded and
        // the panel has rendered, so the panel has to observe it.
        this.suggest = reactive({
            numberOfDays: 0,
            basedOn: null,
            percentFactor: 0,
            suggestToggle: { isOn: false },
            totalEstimatedPrice: 0,
        });
        useSubEnv({
            suggest: this.suggest,
            _computeTotalEstimatedPrice: () => this._computeTotalEstimatedPrice(),
        });
    }

    /** @override to add suggest context and filters if suggest is ON on first load. */
    async load(config) {
        Object.assign(this.suggest, {
            numberOfDays:
                config.context.vendor_suggest_days ?? this.suggest.numberOfDays,
            basedOn: config.context.vendor_suggest_based_on ?? this.suggest.basedOn,
            percentFactor:
                config.context.vendor_suggest_percent ?? this.suggest.percentFactor,
            suggestToggle: getSuggestToggleState(
                config.context.product_catalog_order_state,
            ),
        });
        if (this.suggest.suggestToggle.isOn) {
            config.context["search_default_suggested"] = true;
            config.context["search_default_products_in_purchase_order"] = true;
        }
        await super.load(config);
        if (this.suggest.suggestToggle.isOn) {
            this._computeTotalEstimatedPrice();
        }
    }

    /** @override inside of _notify (but only when searchpanel exists) to add ctx for */
    async _fetchSections() {
        this._editSuggestContext();
        await super._fetchSections(...arguments);
    }

    /** @override to recompute total price and add category_id to domain when selecting a category */
    toggleCategoryValue() {
        super.toggleCategoryValue(...arguments);
        if (this.suggest.suggestToggle.isOn) {
            this._computeTotalEstimatedPrice();
        }
    }

    async _computeTotalEstimatedPrice() {
        this._editSuggestContext();
        const product_prices = await this.orm.searchRead(
            "product.product",
            this.domain,
            ["suggest_estimated_price"],
            { context: this.globalContext },
        );
        this.suggest.totalEstimatedPrice = product_prices.reduce(
            (sum, p) => sum + Number(p.suggest_estimated_price || 0),
            0,
        );
    }

    /**
     * @param {Array[string]} filterNames
     * @param {boolean} turnOn
     */
    toggleFilters(filterNames, turnOn) {
        const searchFilters = new Map(
            Object.values(this.searchItems).map((i) => [i.name, i]),
        );
        const activeFilters = new Set(this.query.map((q) => q.searchItemId));

        const toToggle = [];
        for (const name of filterNames) {
            const item = searchFilters.get(name);
            const isOn = activeFilters.has(item.id);
            if ((turnOn && !isOn) || (!turnOn && isOn)) {
                toToggle.push(item.id);
            }
        }

        for (let i = 0; i < toToggle.length; i++) {
            const isLast = i === toToggle.length - 1;
            this.blockNotification = !isLast;
            this.toggleSearchItem(toToggle[i]);
        }

        if (this.suggest.suggestToggle.isOn) {
            this._computeTotalEstimatedPrice();
        }
        if (toToggle.length === 0) {
            this._notify();
        }
    }

    /** @returns {Object} */
    _editSuggestContext() {
        const suggestContext = {
            suggest_domain: this.domain,
            suggest_based_on: this.suggest.basedOn,
            suggest_days: this.suggest.numberOfDays,
            suggest_percent: this.suggest.percentFactor,
            section_id: this.selectedSection.sectionId ?? false,
        };
        if (!this.suggest.suggestToggle.isOn) {
            for (const k of new Set([...Object.keys(suggestContext)])) {
                delete this.globalContext[k];
            }
        } else {
            this.globalContext = { ...this.globalContext, ...suggestContext };
        }
    }
}
