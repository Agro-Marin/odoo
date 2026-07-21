/** @odoo-module native */
import { PivotRenderer } from "@web/views/pivot/pivot_renderer";

export class AnalyticPivotRenderer extends PivotRenderer {
    /**
     * Override to also resolve the selected id against the per-plan group-by
     * options, which are not top-level entries of `groupByItems`.
     */
    onGroupBySelected({ itemId, optionId }) {
        if (typeof optionId === "number") {
            itemId = optionId;
        }
        let searchItems = this.env.searchModel.getSearchItems(
            (searchItem) =>
                ["groupBy", "dateGroupBy"].includes(searchItem.type) &&
                !searchItem.custom,
        );

        // Add custom groupbys
        for (const [
            fieldName,
            customGroupBy,
        ] of this.model.metaData.customGroupBys.entries()) {
            searchItems.push({ ...customGroupBy, fieldName });
        }
        searchItems = [
            ...searchItems,
            ...searchItems
                .flatMap((f) => f.options)
                .filter((f) => typeof f?.id === "number"),
        ];
        const { fieldName } = searchItems.find(({ id }) => id === itemId);
        this.model.addGroupBy({
            ...this.dropdown.cellInfo,
            fieldName,
            interval: optionId,
        });
    }
}
