// @ts-check
/** @odoo-module native */

/** @module @web/search/search_state */

import { evaluateBooleanExpr } from "@web/core/py_js/py";

export const SPECIAL = Symbol("special");

export const FAVORITE_PRIVATE_GROUP = 1;
export const FAVORITE_SHARED_GROUP = 2;

/**
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
 * @param {[any, Object][]} array
 * @returns {Map<any, Object>}
 */
export function arrayToMap(array) {
    return new Map(array.map(([key, val]) => [key, { ...val }]));
}

/**
 * @param {Function} op
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
 * @param {Object} globalContext
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
