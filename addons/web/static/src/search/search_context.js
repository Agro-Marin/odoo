// @ts-check
/** @odoo-module native */

import { makeContext } from "@web/core/context";
import { evaluateExpr } from "@web/core/py_js/py";
import { _t } from "@web/core/translation";
import { deepCopy } from "@web/core/utils/collections/objects";

/** @import { ActiveItem, AutocompleteValue, QueryGroup, SearchItems } from "./search_types" */

/**
 * @param {unknown} value
 * @returns {boolean}
 */
function isContextDict(value) {
    return typeof value === "object" && value !== null && !Array.isArray(value);
}

/**
 * @param {ActiveItem} activeItem
 * @param {SearchItems} searchItems
 * @returns {Record<string, any>|null}
 */
export function computeSearchItemContext(activeItem, searchItems) {
    const { searchItemId } = activeItem;
    const searchItem = searchItems[searchItemId];
    switch (searchItem.type) {
        case "field": {
            /** @type {Record<string, any>} */
            let context = {};
            if (searchItem.context) {
                const self = (activeItem.autocompleteValues ?? []).map(
                    (/** @type {AutocompleteValue} */ autocompleteValue) =>
                        autocompleteValue.value,
                );
                context = evaluateExpr(searchItem.context, { self });
                if (!isContextDict(context)) {
                    throw new Error(
                        _t("Failed to evaluate the context: %(context)s.", {
                            context: searchItem.context,
                        }),
                    );
                }
            }
            if (searchItem.isDefault && searchItem.fieldType === "many2one") {
                if (searchItem.defaultAutocompleteValue) {
                    context[`default_${searchItem.fieldName}`] =
                        searchItem.defaultAutocompleteValue.value;
                }
            }
            return context;
        }
        case "favorite":
        case "filter":
            return makeContext([searchItem.context && deepCopy(searchItem.context)]);
        default:
            return null;
    }
}

/**
 * @param {QueryGroup[]} groups
 * @param {Record<string, any>} userContext
 * @param {(activeItem: ActiveItem) => Record<string, any>|null} getSearchItemContext
 * @returns {Record<string, any>}
 */
export function computeSearchContext(groups, userContext, getSearchItemContext) {
    const contexts = [userContext];
    for (const group of groups) {
        for (const activeItem of group.activeItems) {
            const context = getSearchItemContext(activeItem);
            if (context) {
                contexts.push(context);
            }
        }
    }
    return makeContext(contexts);
}
