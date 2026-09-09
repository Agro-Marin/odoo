/** @odoo-module native */
import { ProductCatalogKanbanModel } from "@product/product_catalog/kanban_model";

import { getSuggestToggleState } from "./utils.js";

export class PurchaseSuggestCatalogKanbanModel extends ProductCatalogKanbanModel {
    /** @override to reorder records with suggested_qty > 0 to the top, keeping original order. */
    async _loadData(params, ...rest) {
        const sortBySuggested = (list) => {
            const suggested = list.filter((record) => record.suggested_qty > 0);
            const rest = list.filter((record) => !(record.suggested_qty > 0));
            return [...suggested, ...rest];
        };
        const suggest = getSuggestToggleState(
            this.config.context.product_catalog_order_state,
        );
        const result = await super._loadData(params, ...rest);
        if (!suggest.isOn || !result.records.some((r) => r.suggested_qty > 0)) {
            return result;
        }
        if (!params.isMonoRecord) {
            if (params.groupBy?.length) {
                for (const group of result.groups) {
                    group.list.records = sortBySuggested(group.list.records);
                }
            } else {
                result.records = sortBySuggested(result.records);
            }
        }
        return result;
    }

    _getOrderLinesInfoParams(loadParams, productIds) {
        const base = super._getOrderLinesInfoParams(loadParams, productIds);
        return { ...base, ...loadParams.context };
    }
}
