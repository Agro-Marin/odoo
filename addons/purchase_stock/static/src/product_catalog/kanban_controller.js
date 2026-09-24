/** @odoo-module native */
import { ProductCatalogKanbanController } from "@product/product_catalog/kanban_controller";
import {
    provideProductCatalogContext,
    useProductCatalogContext,
} from "@product/product_catalog/product_catalog_context";
import { browser } from "@web/core/browser/browser";
import { useDebounced } from "@web/core/utils/timing";
import { useSearchModel } from "@web/search/search_model";

import { SUGGEST_TOGGLE_STORAGE_KEY } from "./utils.js";

export class PurchaseSuggestCatalogKanbanController extends ProductCatalogKanbanController {
    setup() {
        super.setup();
        this.searchModel = useSearchModel();
        const parentCatalog = useProductCatalogContext();
        this.suggest = parentCatalog.suggest;
        this._computeTotalEstimatedPrice = parentCatalog._computeTotalEstimatedPrice;
        Object.assign(this.suggest, {
            currencyId: this.props.context.product_catalog_currency_id,
            digits: this.props.context.product_catalog_digits,
            poState: this.props.context.product_catalog_order_state,
            vendorName: this.props.context.vendor_name,
            warehouse_id: this.props.context.warehouse_id,
        });

        provideProductCatalogContext({
            addAllProducts: () => this.onAddAll(),
            toggleSuggest: () => this.toggleSuggest(),
            reloadKanban: () => this._kanbanReload(),
            debouncedReloadKanban: useDebounced(async () => {
                this._kanbanReload();
            }, 500),
        });
    }

    async _kanbanReload() {
        await this.searchModel.invalidateSections();
        await this._computeTotalEstimatedPrice();
    }

    async onAddAll() {
        const { searchModel } = this.env;
        const { sectionId } = searchModel.selectedSection;
        const lineCountChange = await this.model.orm.call(
            "purchase.order",
            "action_purchase_order_suggest",
            [this.props.context.order_id],
            { context: searchModel.globalContext },
        );
        searchModel.toggleFilters(["suggested", "products_in_purchase_order"], true);
        searchModel.trigger("section-line-count-change", {
            sectionId,
            lineCountChange,
        });
    }

    toggleSuggest() {
        this.suggest.suggestToggle.isOn = !this.suggest.suggestToggle.isOn;
        browser.localStorage.setItem(
            SUGGEST_TOGGLE_STORAGE_KEY,
            JSON.stringify({ isOn: this.suggest.suggestToggle.isOn }),
        );
        this.searchModel.toggleFilters(
            ["suggested", "products_in_purchase_order"],
            this.suggest.suggestToggle.isOn,
        );
    }
}
