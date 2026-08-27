// @ts-check
/** @odoo-module native */

import { Domain } from "@web/core/domain";
import { _t } from "@web/core/translation";

import { computeActiveItemDomains } from "./search_domain.js";
import { SPECIAL } from "./search_state.js";
import { BACKEND_INTERVAL_OPTIONS } from "./utils/dates.js";
import { FACET_COLORS, FACET_ICONS } from "./utils/misc.js";

/** @import { Facet, QueryGroup, SearchItems } from "./search_types" */

/**
 * @param {string} intervalId
 * @returns {string}
 */
function intervalDescription(intervalId) {
    return String(BACKEND_INTERVAL_OPTIONS[intervalId]?.description ?? intervalId);
}

/**
 * @param {string} type
 * @param {string|false} orderByCount
 * @returns {string}
 */
function groupByIcon(type, orderByCount) {
    if (type === "groupBy" && orderByCount) {
        return FACET_ICONS[orderByCount === "Asc" ? "groupByAsc" : "groupByDesc"];
    }
    return FACET_ICONS[type];
}

/**
 * @param {QueryGroup} group
 * @param {SearchItems} searchItems
 * @param {Function} getDateFilterDomain
 * @returns {{values: string[], title: string|undefined, type: string|undefined, tooltip: string|undefined}}
 */
function readGroupLabels(group, searchItems, getDateFilterDomain) {
    const values = [];
    let title;
    let type;
    let tooltip;
    for (const activeItem of group.activeItems) {
        const searchItem = searchItems[activeItem.searchItemId];
        tooltip ||= searchItem.tooltip;
        switch (searchItem.type) {
            case "field_property":
            case "field": {
                type = "field";
                title = searchItem.description;
                for (const autocompleteValue of activeItem.autocompleteValues ?? []) {
                    values.push(autocompleteValue.label);
                }
                break;
            }
            case "groupBy": {
                type = "groupBy";
                values.push(searchItem.description ?? "");
                break;
            }
            case "dateGroupBy": {
                type = "groupBy";
                for (const intervalId of activeItem.intervalIds ?? []) {
                    values.push(
                        `${searchItem.description}: ${intervalDescription(intervalId)}`,
                    );
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
                values.push(searchItem.description ?? "");
            }
        }
    }
    return { values, title, type, tooltip };
}

/**
 * @param {string[]} defaultGroupBy
 * @param {Record<string, any>} searchViewFields
 * @param {string|false} orderByCount
 * @returns {Facet}
 */
function buildDefaultGroupByFacet(defaultGroupBy, searchViewFields, orderByCount) {
    return {
        groupId: SPECIAL,
        type: "groupBy",
        values: defaultGroupBy.map((gb) => {
            const [fieldName, interval] = gb.split(":");
            const string = searchViewFields[fieldName]?.string ?? fieldName;
            return interval ? `${string}: ${intervalDescription(interval)}` : string;
        }),
        separator: ">",
        icon: groupByIcon("groupBy", orderByCount),
        color: FACET_COLORS.groupBy,
    };
}

/**
 * @param {object} params
 * @param {QueryGroup[]} params.groups
 * @param {SearchItems} params.searchItems
 * @param {Function} params.getSearchItemDomain
 * @param {Function} params.getDateFilterDomain
 * @param {string|false} params.orderByCount
 * @param {string[]} params.globalGroupBy
 * @param {string[]} [params.defaultGroupBy]
 * @param {Record<string, any>} params.searchViewFields
 * @param {string} [params.viewType]
 * @returns {Facet[]}
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
    /** @type {Facet[]} */
    const facets = [];
    for (const group of groups) {
        const groupActiveItemDomains = computeActiveItemDomains(
            group,
            getSearchItemDomain,
        );
        const { values, title, type, tooltip } = readGroupLabels(
            group,
            searchItems,
            getDateFilterDomain,
        );
        /** @type {Facet} */
        const facet = {
            groupId: group.id,
            type,
            values,
            separator: type === "groupBy" ? ">" : _t("or"),
        };
        if (type === "field") {
            facet.title = title;
        } else if (type) {
            facet.icon = groupByIcon(type, orderByCount);
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

    const hasAGroupByFacet = facets.some((f) => f.type === "groupBy");
    if (
        !hasAGroupByFacet &&
        !globalGroupBy.length &&
        defaultGroupBy &&
        viewType !== "kanban"
    ) {
        facets.unshift(
            buildDefaultGroupByFacet(defaultGroupBy, searchViewFields, orderByCount),
        );
    }
    return facets;
}
