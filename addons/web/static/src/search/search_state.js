// @ts-check
/** @odoo-module native */

/** @module @web/search/search_state - State serialization, shared constants, and section helpers for SearchModel */

// Shared constants

/** Sentinel for the default-groupBy facet (not a real groupId). */
export const SPECIAL = Symbol("special");

export const FAVORITE_PRIVATE_GROUP = 1;
export const FAVORITE_SHARED_GROUP = 2;

// Section helpers

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
            return values?.size > 1; // false item ignored
        }
        case "filter": {
            return values?.size > 0;
        }
    }
}

// State serialization

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
 * Deserialize an array of [key, value] pairs back to a Map.
 *
 * @param {[any, Object][]} array
 * @returns {Map<any, Object>}
 */
export function arrayToMap(array) {
    return new Map(array);
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
    } = source;

    target.nextGroupId = nextGroupId;
    target.nextGroupNumber = nextGroupNumber;
    target.nextId = nextId;

    // Deep-copy so the exported/imported state does not alias the live model:
    // the sole caller (SearchModel.exportState) stringifies the result
    // immediately, but any consumer that reads the snapshot lazily (or mutates
    // the model afterwards) would otherwise observe the live, still-mutating
    // state.
    target.query = structuredClone(query);
    target.searchItems = structuredClone(searchItems);
    // primitive ("Asc" | "Desc" | false) — drives the groupBy facet sort icon
    // and the injected {name:"__count"} orderBy; must survive export/import so a
    // "sort by count" choice persists across breadcrumb restore / back-forward.
    target.orderByCount = orderByCount;

    // Deep-copy: searchPanelInfo was aliased outright, so a lazily-read export
    // saw later mutations. structuredClone is safe in both directions (it just
    // gives the target a fresh, plain copy).
    target.searchPanelInfo = structuredClone(searchPanelInfo);

    // ``op`` (mapToArray/arrayToMap) converts each section, its ``values`` and
    // ``groups`` Maps ONE level deep. This is NOT a full deep snapshot: nested
    // arrays (e.g. ``childrenIds``) and value objects shared between
    // ``filter.values`` and ``group.values`` stay referenced. Safe today
    // because the only consumer stringifies immediately — do not read the
    // export lazily and then mutate the model, or deep-copy here first.
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
}

// Search defaults

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
