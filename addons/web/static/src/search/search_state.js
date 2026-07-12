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
    //
    // JSON round-trip, NOT structuredClone: search items/query carry favorite
    // contexts whose values may be py_js instances (PyDate/PyDateTime from
    // context_today() et al.). structuredClone severs their prototype, turning
    // a PyDate into a bare {year,month,day} that corrupts every downstream RPC
    // context; JSON.stringify instead invokes their toJSON() (-> "2026-07-12").
    // It also can't throw on non-cloneable values (e.g. a dynamic filter's
    // domain function), which structuredClone would.
    target.query = JSON.parse(JSON.stringify(query));
    target.searchItems = JSON.parse(JSON.stringify(searchItems));
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
    // arrays (e.g. ``childrenIds``) stay referenced, and each value object is
    // copied SEPARATELY for ``filter.values`` and ``group.values`` — the
    // export breaks the identity invariant createFilterTree establishes
    // between them (restored below on import). Safe on export because the
    // only consumer stringifies immediately — do not read the export lazily
    // and then mutate the model, or deep-copy here first.
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
        // Re-establish `filter.values.get(id) === group.values.get(id)`:
        // toggleFilterValues mutates filter.values while computeFilterDomain
        // reads group.values, so a grouped section that is not refetched after
        // import (expand sections without counters) would otherwise ignore
        // toggles until the next refetch re-aliases the two Maps.
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
