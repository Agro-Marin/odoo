// @ts-check
/** @odoo-module native */

/** @module search/search_domain */

import { Domain } from "@web/core/domain";

import { constructDateDomain } from "./utils/dates.js";
/**
 * @param {Iterable} categories
 * @param {Object} searchViewFields
 * @param {number} [excludedCategoryId]
 * @returns {Array[]}
 */
export function computeCategoryDomain(
    categories,
    searchViewFields,
    excludedCategoryId,
) {
    const domain = [];
    for (const category of categories) {
        if (category.id === excludedCategoryId || !category.activeValueId) {
            continue;
        }
        const field = searchViewFields[category.fieldName];
        const operator =
            field.type === "many2one" && category.parentField ? "child_of" : "=";
        domain.push([category.fieldName, operator, category.activeValueId]);
    }
    return domain;
}

/**
 * @param {Iterable} filters
 * @param {number} [excludedFilterId]
 * @returns {Array[]}
 */
export function computeFilterDomain(filters, excludedFilterId) {
    const domain = [];

    function addCondition(fieldName, valueMap) {
        const ids = [];
        for (const [valueId, value] of valueMap) {
            if (value.checked) {
                ids.push(valueId);
            }
        }
        if (ids.length) {
            domain.push([fieldName, "in", ids]);
        }
    }

    for (const filter of filters) {
        if (filter.id === excludedFilterId) {
            continue;
        }
        const { fieldName, groups, values } = filter;
        if (groups) {
            for (const group of groups.values()) {
                addCondition(fieldName, group.values);
            }
        } else {
            addCondition(fieldName, values);
        }
    }
    return domain;
}

/**
 * @param {Object} filter
 * @param {Object} searchViewFields
 * @returns {Object|Array[]|null}
 */
export function computeGroupDomain(filter, searchViewFields) {
    const { fieldName, groups, enableCounters } = filter;
    const { type: fieldType } = searchViewFields[fieldName];

    if (!["many2one", "many2many"].includes(fieldType)) {
        return null;
    }

    if (!enableCounters || !groups) {
        return { many2one: [], many2many: {} }[fieldType];
    }

    let groupDomain = null;
    if (fieldType === "many2one") {
        for (const group of groups.values()) {
            const valueIds = [];
            let active = false;
            for (const [valueId, value] of group.values) {
                valueIds.push(valueId);
                if (value.checked) {
                    active = true;
                }
            }
            if (active) {
                if (groupDomain) {
                    groupDomain = [[0, "=", 1]];
                    break;
                } else {
                    groupDomain = [[fieldName, "in", valueIds]];
                }
            }
        }
    } else if (fieldType === "many2many") {
        const checkedValueIds = new Map();
        groups.forEach(({ values }, groupId) => {
            values.forEach(({ checked }, valueId) => {
                if (checked) {
                    if (!checkedValueIds.has(groupId)) {
                        checkedValueIds.set(groupId, []);
                    }
                    /** @type {any[]} */ (checkedValueIds.get(groupId)).push(valueId);
                }
            });
        });
        /** @type {Record<string, any[]>} */
        const byGroup = {};
        for (const [gId, ids] of checkedValueIds.entries()) {
            for (const groupId of groups.keys()) {
                if (gId !== groupId) {
                    const key = JSON.stringify(groupId);
                    (byGroup[key] ??= []).push([fieldName, "in", ids]);
                }
            }
        }
        groupDomain = byGroup;
    }
    return groupDomain;
}

/**
 * @param {Object} field
 * @param {Object[]} autocompleteValues
 * @returns {Domain}
 */
export function computeFieldDomain(field, autocompleteValues) {
    const filterDomain = field.filterDomain ? new Domain(field.filterDomain) : null;
    const domains = autocompleteValues.map(({ label, value, operator }) => {
        let domain;
        if (filterDomain) {
            domain = filterDomain.toList({
                self: label.trim(),
                raw_value: value,
            });
        } else if (field.type === "field") {
            domain = [[field.fieldName, operator, value]];
        } else if (field.type === "field_property") {
            domain = [
                field.propertyDomain,
                [
                    `${field.fieldName}.${field.propertyFieldDefinition.name}`,
                    operator,
                    value,
                ],
            ];
        }
        return new Domain(domain);
    });
    return Domain.or(domains);
}

/**
 * @param {Object} referenceMoment
 * @param {Object} dateFilter
 * @param {Array} generatorIds
 * @param {string} [key="domain"]
 * @returns {Domain|string}
 */
export function computeDateFilterDomain(
    referenceMoment,
    dateFilter,
    generatorIds,
    key = "domain",
) {
    const dateFilterRange = constructDateDomain(
        referenceMoment,
        dateFilter,
        generatorIds,
    );
    return dateFilterRange[key];
}

/**
 * @param {Object} activeItem
 * @param {Object} searchItems
 * @param {Object} referenceMoment
 * @returns {Domain|string|null}
 */
export function computeSearchItemDomain(activeItem, searchItems, referenceMoment) {
    const { searchItemId } = activeItem;
    const searchItem = searchItems[searchItemId];
    switch (searchItem.type) {
        case "field_property":
        case "field":
            return computeFieldDomain(searchItem, activeItem.autocompleteValues);
        case "dateFilter":
            return computeDateFilterDomain(
                referenceMoment,
                searchItem,
                activeItem.generatorIds,
            );
        case "filter":
        case "favorite":
            return searchItem.domain;
        default:
            return null;
    }
}

/**
 * @param {Array[]} categoryDomain
 * @param {Array[]} filterDomain
 * @returns {Domain}
 */
export function computeSearchPanelDomain(categoryDomain, filterDomain) {
    return Domain.and(/** @type {any} */ ([categoryDomain, filterDomain]));
}

/**
 * @param {Object} params
 * @param {Object[]} params.groups
 * @param {Domain|Array} params.globalDomain
 * @param {boolean} params.withGlobal
 * @param {boolean} params.withSearchPanel
 * @param {Function} params.getSearchItemDomain
 * @param {Function} params.getSearchPanelDomain
 * @param {Object} params.domainEvalContext
 * @param {boolean} params.raw
 * @returns {any[]|Domain}
 */
/**
 * @param {Object} group
 * @param {Function} getSearchItemDomain
 * @returns {Domain[]}
 */
export function computeActiveItemDomains(group, getSearchItemDomain) {
    const domains = [];
    for (const activeItem of group.activeItems) {
        const domain = getSearchItemDomain(activeItem);
        if (domain) {
            domains.push(domain);
        }
    }
    return domains;
}

export function computeDomain({
    groups,
    globalDomain,
    withGlobal,
    withSearchPanel,
    getSearchItemDomain,
    getSearchPanelDomain,
    domainEvalContext,
    raw,
}) {
    const domains = [];
    if (withGlobal) {
        domains.push(globalDomain);
    }
    for (const group of groups) {
        domains.push(Domain.or(computeActiveItemDomains(group, getSearchItemDomain)));
    }
    if (withSearchPanel) {
        domains.push(getSearchPanelDomain());
    }
    const domain = Domain.and(domains);
    if (raw) {
        return domain;
    }
    return JSON.parse(JSON.stringify(domain.toList(domainEvalContext)));
}
