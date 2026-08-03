// @ts-check
/** @odoo-module native */

/** @module search/search_context */

/**
 * @param {Object} activeItem
 * @param {Object} searchItems
 * @returns {Object|null}
 */

import { makeContext } from "@web/core/context";
import { evaluateExpr } from "@web/core/py_js/py";
import { _t } from "@web/core/translation";
import { deepCopy } from "@web/core/utils/collections/objects";
export function computeSearchItemContext(activeItem, searchItems) {
    const { searchItemId } = activeItem;
    const searchItem = searchItems[searchItemId];
    switch (searchItem.type) {
        case "field": {
            let context = {};
            if (searchItem.context) {
                const self = activeItem.autocompleteValues.map(
                    (autocompleteValue) => autocompleteValue.value,
                );
                context = evaluateExpr(searchItem.context, { self });
                if (typeof context !== "object") {
                    throw new Error(
                        _t("Failed to evaluate the context: %(context)s.", {
                            context: searchItem.context,
                        }),
                    );
                }
            }
            if (searchItem.isDefault && searchItem.fieldType === "many2one") {
                context[`default_${searchItem.fieldName}`] =
                    searchItem.defaultAutocompleteValue.value;
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
 * @param {Object[]} groups
 * @param {Object} userContext
 * @param {Function} getSearchItemContext
 * @returns {Object}
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
