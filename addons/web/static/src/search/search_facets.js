// @ts-check
/** @odoo-module native */

/** @module search/search_facets - Facet building utilities for SearchModel */

import { Domain } from "@web/core/domain";
import { _t } from "@web/core/l10n/translation";

import { computeActiveItemDomains } from "./search_domain.js";
import { SPECIAL } from "./search_state.js";
import { INTERVAL_OPTIONS } from "./utils/dates.js";
import { FACET_COLORS, FACET_ICONS } from "./utils/misc.js";
/**
 * Build the facets array from active query groups.
 *
 * @param {Object} params
 * @param {Object[]} params.groups - active query groups
 * @param {Object} params.searchItems
 * @param {Function} params.getSearchItemDomain - (activeItem) => Domain|null
 * @param {Function} params.getDateFilterDomain - (searchItem, generatorIds, key) => string
 * @param {string|false} params.orderByCount
 * @param {string[]} params.globalGroupBy
 * @param {string[]} [params.defaultGroupBy]
 * @param {Object} params.searchViewFields
 * @param {string} [params.viewType]
 * @returns {Object[]}
 */
export function buildFacets({
    groups,
    searchItems,
    getSearchItemDomain,
    getDateFilterDomain,
    orderByCount,
    globalGroupBy,
    defaultGroupBy,
    searchViewFields,
    viewType,
}) {
    const facets = [];
    for (const group of groups) {
        const groupActiveItemDomains = computeActiveItemDomains(
            group,
            getSearchItemDomain,
        );
        const values = [];
        let title;
        let type;
        let tooltip;
        for (const activeItem of group.activeItems) {
            const searchItem = searchItems[activeItem.searchItemId];
            // ||=: keep the first tooltip found in the group — a later item
            // without one (e.g. OR'd split filters) must not erase it.
            tooltip ||= searchItem.tooltip;
            switch (searchItem.type) {
                case "field_property":
                case "field": {
                    type = "field";
                    title = searchItem.description;
                    for (const autocompleteValue of activeItem.autocompleteValues) {
                        values.push(autocompleteValue.label);
                    }
                    break;
                }
                case "groupBy": {
                    type = "groupBy";
                    values.push(searchItem.description);
                    break;
                }
                case "dateGroupBy": {
                    type = "groupBy";
                    for (const intervalId of activeItem.intervalIds) {
                        const option = INTERVAL_OPTIONS[intervalId];
                        if (!option) {
                            continue;
                        }
                        const { description } = option;
                        values.push(`${searchItem.description}: ${description}`);
                    }
                    break;
                }
                case "dateFilter": {
                    type = "filter";
                    const periodDescription = getDateFilterDomain(
                        searchItem,
                        activeItem.generatorIds,
                        "description",
                    );
                    values.push(`${searchItem.description}: ${periodDescription}`);
                    break;
                }
                default: {
                    type = searchItem.type;
                    values.push(searchItem.description);
                }
            }
        }
        const facet = {
            groupId: group.id,
            type,
            values,
            separator: type === "groupBy" ? ">" : _t("or"),
        };
        if (type === "field") {
            facet.title = title;
        } else {
            if (type === "groupBy" && orderByCount) {
                facet.icon =
                    FACET_ICONS[orderByCount === "Asc" ? "groupByAsc" : "groupByDesc"];
            } else {
                facet.icon = FACET_ICONS[type];
            }
            facet.color = FACET_COLORS[type];
        }
        if (tooltip) {
            facet.tooltip = tooltip;
        }
        if (groupActiveItemDomains.length) {
            facet.domain = Domain.or(groupActiveItemDomains).toString();
        }
        facets.push(facet);
    }

    // Add default groupBy facet if none active
    const hasAGroupByFacet = facets.some((f) => f.type === "groupBy");
    if (
        !hasAGroupByFacet &&
        !globalGroupBy.length &&
        defaultGroupBy &&
        viewType !== "kanban"
    ) {
        facets.unshift({
            groupId: SPECIAL,
            type: "groupBy",
            values: defaultGroupBy.map((gb) => {
                const [fieldName, interval] = gb.split(":");
                // A default groupBy may reference a field absent from the search
                // view (dotted/related, or simply removed); fall back to the raw
                // name instead of throwing and poisoning the whole control panel.
                const string = searchViewFields[fieldName]?.string ?? fieldName;
                if (interval) {
                    const option = INTERVAL_OPTIONS[interval];
                    if (!option) {
                        return string;
                    }
                    const { description } = option;
                    return `${string}:${description}`;
                }
                return string;
            }),
            separator: ">",
            icon: FACET_ICONS.groupBy,
            color: FACET_COLORS.groupBy,
        });
    }
    return facets;
}
