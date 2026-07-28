// @ts-check
/** @odoo-module native */

/** @module @web/search/search_state - State serialization, shared constants, and section helpers for SearchModel */

import { evaluateBooleanExpr } from "@web/core/py_js/py";

/** Sentinel for the default-groupBy facet (not a real groupId). */
export const SPECIAL = Symbol("special");

export const FAVORITE_PRIVATE_GROUP = 1;
export const FAVORITE_SHARED_GROUP = 2;

/**
 * Whether a search-panel section has displayable values.
 *
 * @param {Object} section
 * @returns {boolean}
 */
export function hasValues(section) {
    const { errorMsg, type, values } = section;
    if (errorMsg) {
        return true;
    }
    switch (type) {
        case "category": {
            return values?.size > 1;
        }
        case "filter": {
            return values?.size > 0;
        }
        default: {
            return false;
        }
    }
}

/**
 * Evaluate a search-view `invisible` expression the same way every other view
 * modifier is evaluated (`bool(...)`, so an empty list reads as visible).
 *
 * The expression is view data written by whoever authored the arch, not an
 * invariant of this module. An unevaluatable one used to propagate out of
 * `getSearchItems`, which is read lazily: the mount survives, and the throw
 * lands as an Owl lifecycle error the first time the user opens the search-bar
 * menu or types in the input. Hiding nothing and saying why keeps the failure
 * to the one item that caused it.
 *
 * @param {string | undefined} expr
 * @param {Object} evalContext
 * @returns {boolean}
 */
export function isInvisible(expr, evalContext) {
    try {
        return evaluateBooleanExpr(expr, evalContext);
    } catch (error) {
        console.warn(`[search] ignoring invisible="${expr}": ${error.message}`);
        return false;
    }
}

/**
 * Serialize a Map to an array of [key, shallowCopy(value)] pairs.
 *
 * @param {Map<any, Object>} map
 * @returns {Array[]}
 */
export function mapToArray(map) {
    const result = [];
    for (const [key, val] of map) {
        const valCopy = { ...val };
        result.push([key, valCopy]);
    }
    return result;
}

/**
 * Deserialize an array of [key, value] pairs back to a Map, copying each value
 * the way {@link mapToArray} does on the way out.
 *
 * Without the copy the imported model shares its section/value objects with the
 * state object it was handed, and `execute` then rewrites that object's
 * `values`/`groups` arrays into Maps in place — so `load({state})` corrupted a
 * caller-owned state instead of reading it. Only `WithSearch` hid this, by
 * always passing a fresh `JSON.parse` result.
 *
 * @param {[any, Object][]} array
 * @returns {Map<any, Object>}
 */
export function arrayToMap(array) {
    return new Map(array.map(([key, val]) => [key, { ...val }]));
}

/**
 * Copy SearchModel state between two objects, converting section/group
 * Maps via the provided `op` (either `mapToArray` or `arrayToMap`).
 *
 * @param {Function} op - mapToArray (export) or arrayToMap (import)
 * @param {Object} source
 * @param {Object} target
 */
export function execute(op, source, target) {
    const {
        query,
        nextId,
        nextGroupId,
        nextGroupNumber,
        searchItems,
        searchPanelInfo,
        sections,
        orderByCount,
        defaultGroupByRemoved,
    } = source;

    target.nextGroupId = nextGroupId;
    target.nextGroupNumber = nextGroupNumber;
    target.nextId = nextId;

    target.defaultGroupByRemoved = defaultGroupByRemoved;

    // JSON round-trip, not structuredClone: the exported state is handed
    // straight to JSON.stringify by WithSearch.getGlobalState, so dropping what
    // JSON cannot represent is the intended semantics — and structuredClone
    // would throw on a searchItem holding anything non-cloneable instead.
    target.query = JSON.parse(JSON.stringify(query));
    target.searchItems = JSON.parse(JSON.stringify(searchItems));
    target.orderByCount = orderByCount;

    target.searchPanelInfo = structuredClone(searchPanelInfo);

    target.sections = op(sections);
    for (const [, section] of target.sections) {
        section.values = op(section.values);
        if (section.groups) {
            section.groups = op(section.groups);
            for (const [, group] of section.groups) {
                group.values = op(group.values);
            }
        }
    }
    if (op === arrayToMap) {
        for (const [, section] of target.sections) {
            if (!section.groups) {
                continue;
            }
            for (const [, group] of section.groups) {
                for (const valueId of group.values.keys()) {
                    const value = section.values.get(valueId);
                    if (value) {
                        group.values.set(valueId, value);
                    }
                }
            }
        }
    }
}

/**
 * Extract `search_default_*` and `searchpanel_default_*` keys from a
 * global context object.  Matched keys are **deleted** from `globalContext`
 * so they don't leak into downstream contexts.
 *
 * @param {Object} globalContext - mutated in place
 * @returns {{ searchDefaults: Object, searchPanelDefaults: Object }}
 */
export function extractSearchDefaults(globalContext) {
    const searchDefaults = {};
    const searchPanelDefaults = {};
    for (const key of Object.keys(globalContext)) {
        const defaultValue = globalContext[key];
        const searchDefaultMatch = /^search_default_(.*)$/.exec(key);
        if (searchDefaultMatch) {
            if (defaultValue) {
                searchDefaults[searchDefaultMatch[1]] = defaultValue;
            }
            delete globalContext[key];
            continue;
        }
        const searchPanelDefaultMatch = /^searchpanel_default_(.*)$/.exec(key);
        if (searchPanelDefaultMatch) {
            searchPanelDefaults[searchPanelDefaultMatch[1]] = defaultValue;
            delete globalContext[key];
        }
    }
    return { searchDefaults, searchPanelDefaults };
}
