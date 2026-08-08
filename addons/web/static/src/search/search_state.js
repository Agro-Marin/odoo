// @ts-check
/** @odoo-module native */

/** @module @web/search/search_state */

import { evaluateBooleanExpr } from "@web/core/py_js/py";

/** @import { DomainListRepr } from "@web/core/domain" */

export const SPECIAL = Symbol("special");

/**
 * The version written into every exported state. Bump it when a key is added,
 * removed or reshaped, and teach `SearchModel._importState` the transition.
 *
 * History:
 * - (absent): the pre-versioning shape — `SearchModelState` minus `version`,
 *   `searchDomain` and `propertySearchViewFields`. Still importable: those
 *   keys are optional, and their absence reproduces the old behavior.
 * - 2: added `version`, `searchDomain` (restore no longer refetches search
 *   panel sections whose domain did not change) and
 *   `propertySearchViewFields` (property search items resolve their fields
 *   again after a restore).
 */
export const SEARCH_MODEL_STATE_VERSION = 2;

export const FAVORITE_PRIVATE_GROUP = 1;
export const FAVORITE_SHARED_GROUP = 2;

/**
 * @param {Record<string, any>} section
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
 * @param {Record<string, any>} evalContext
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
 * @param {Map<any, Record<string, any>>} map
 * @returns {any[][]}
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
 * @typedef {Object} SearchModelState
 * The serialized form of a `SearchModel`, as produced by `exportState()` and
 * consumed by `_importState()`. The whole object must survive a JSON
 * round-trip: `WithSearch` stores it with `JSON.stringify` in the action's
 * `globalState`, and `knowledge` persists that string in a database field —
 * exported states outlive the build that wrote them.
 *
 * Three serialization strategies coexist, one per kind of data — do not unify
 * them:
 * - **JSON round-trip** (`query`, `searchItems`, `searchDomain`,
 *   `propertySearchViewFields`): deep-copies while proving the data is
 *   JSON-safe at export time, where a failure is attributable, rather than at
 *   `JSON.stringify` time in a consumer.
 * - **structuredClone** (`searchPanelInfo`): a small flat holder that needs a
 *   decoupled copy but no JSON guarantee of its own — it contains only
 *   booleans, strings and arrays thereof.
 * - **Map↔Array** (`sections`): section/group values live in `Map`s, which
 *   JSON cannot represent; they are flattened to `[key, value]` entry arrays
 *   on export and rebuilt on import, where group values are re-aliased onto
 *   the section's value objects so a checkbox toggle stays visible through
 *   both paths.
 *
 * @property {number} [version] `SEARCH_MODEL_STATE_VERSION` at export time;
 *  absent on states exported before versioning (imported as the legacy shape).
 * @property {Object[]} query the active query elements (JSON round-trip).
 * @property {string|false} orderByCount
 * @property {boolean} [defaultGroupByRemoved]
 * @property {Object<number, Object>} searchItems by id (JSON round-trip).
 * @property {number} nextId
 * @property {number} nextGroupId
 * @property {number} nextGroupNumber
 * @property {Object} [searchPanelInfo] structuredClone; optional because
 *  foreign states (an arbitrary `doAction` `globalState.searchModel`, or
 *  states serialized before the key existed) may lack it — `_importState`
 *  falls back to the arch parser's defaults.
 * @property {[number, Object][]} sections search panel sections (Map↔Array).
 * @property {DomainListRepr} [searchDomain] the domain the section data was
 *  last fetched against. Restoring it lets `_reloadSections`' `deepEqual`
 *  recognize an unchanged domain and skip refetching. Absent when the source
 *  model never computed one (no search panel) and on legacy states, where the
 *  first reload after a restore refetches, as it always did.
 * @property {Object<string, Object>} [propertySearchViewFields] the
 *  `searchViewFields` entries derived from property definitions (JSON
 *  round-trip). They are created at runtime by `fillSearchViewItemsProperty`,
 *  so the search view description reloaded on restore does not contain them —
 *  without this key, restored property search items no longer resolve their
 *  fields. Absent on legacy states.
 */

/**
 * Query concern: what the user asked for.
 *
 * @param {Record<string, any>} source
 * @returns {Partial<SearchModelState>}
 */
export function queryToState(source) {
    return {
        query: JSON.parse(JSON.stringify(source.query)),
        orderByCount: source.orderByCount,
        defaultGroupByRemoved: source.defaultGroupByRemoved,
    };
}

/**
 * @param {Partial<SearchModelState>} state
 * @param {Record<string, any>} target
 */
export function queryFromState(state, target) {
    target.query = JSON.parse(JSON.stringify(state.query));
    target.orderByCount = state.orderByCount;
    target.defaultGroupByRemoved = state.defaultGroupByRemoved;
}

/**
 * Items concern: the search items the query indexes into, and the id counters
 * that keep newly created items from colliding with restored ones.
 *
 * @param {Record<string, any>} source
 * @returns {Partial<SearchModelState>}
 */
export function itemsToState(source) {
    return {
        searchItems: JSON.parse(JSON.stringify(source.searchItems)),
        nextId: source.nextId,
        nextGroupId: source.nextGroupId,
        nextGroupNumber: source.nextGroupNumber,
    };
}

/**
 * @param {Partial<SearchModelState>} state
 * @param {Record<string, any>} target
 */
export function itemsFromState(state, target) {
    target.searchItems = JSON.parse(JSON.stringify(state.searchItems));
    target.nextId = state.nextId;
    target.nextGroupId = state.nextGroupId;
    target.nextGroupNumber = state.nextGroupNumber;
}

/**
 * Panel concern: the search panel's sections, its display metadata, and the
 * domain its data was last fetched against.
 *
 * @param {Record<string, any>} source
 * @returns {Partial<SearchModelState>}
 */
export function panelToState(source) {
    /** @type {Partial<SearchModelState>} */
    const state = {
        searchPanelInfo: structuredClone(source.searchPanelInfo),
        sections: sectionsToState(source.sections),
    };
    if (source.searchDomain !== undefined) {
        state.searchDomain = JSON.parse(JSON.stringify(source.searchDomain));
    }
    return state;
}

/**
 * @param {Partial<SearchModelState>} state
 * @param {Record<string, any>} target
 */
export function panelFromState(state, target) {
    target.searchPanelInfo = structuredClone(state.searchPanelInfo);
    target.sections = sectionsFromState(
        /** @type {[number, Object][]} */ (state.sections),
    );
    if (state.searchDomain !== undefined) {
        target.searchDomain = JSON.parse(JSON.stringify(state.searchDomain));
    }
}

/**
 * @param {Map<number, Record<string, any>>} sections
 * @returns {[number, Record<string, any>][]}
 */
function sectionsToState(sections) {
    const result = /** @type {[number, Record<string, any>][]} */ (
        mapToArray(sections)
    );
    for (const [, section] of result) {
        section.values = mapToArray(section.values);
        if (section.groups) {
            section.groups = mapToArray(section.groups);
            for (const [, group] of section.groups) {
                group.values = mapToArray(group.values);
            }
        }
    }
    return result;
}

/**
 * @param {[number, Object][]} sections
 * @returns {Map<number, Object>}
 */
function sectionsFromState(sections) {
    const result = arrayToMap(sections);
    for (const [, section] of result) {
        section.values = arrayToMap(section.values);
        if (section.groups) {
            section.groups = arrayToMap(section.groups);
            for (const [, group] of section.groups) {
                group.values = arrayToMap(group.values);
                for (const valueId of group.values.keys()) {
                    const value = section.values.get(valueId);
                    if (value) {
                        group.values.set(valueId, value);
                    }
                }
            }
        }
    }
    return result;
}

/**
 * Properties concern: the `searchViewFields` entries derived from property
 * definitions. Unlike the other concerns this one exports a *subset* of a
 * model property — the arch-derived entries of `searchViewFields` are reloaded
 * from the view description and must not be overwritten by stale copies.
 *
 * @param {Record<string, any>} source
 * @returns {Partial<SearchModelState>}
 */
export function propertiesToState(source) {
    /** @type {Object<string, Object>} */
    const propertySearchViewFields = {};
    for (const [name, field] of Object.entries(source.searchViewFields || {})) {
        if (field.relatedPropertyField) {
            propertySearchViewFields[name] = JSON.parse(JSON.stringify(field));
        }
    }
    return { propertySearchViewFields };
}

/**
 * @param {Partial<SearchModelState>} state
 * @param {Record<string, any>} target
 */
export function propertiesFromState(state, target) {
    if (!state.propertySearchViewFields) {
        // Legacy state: the entries were not exported. The restored property
        // search items resolve their fields again once a properties fetch
        // refills them, as before versioning.
        return;
    }
    target.searchViewFields ||= {};
    for (const [name, field] of Object.entries(state.propertySearchViewFields)) {
        if (name in target.searchViewFields) {
            continue;
        }
        const copy = JSON.parse(JSON.stringify(field));
        // Re-alias the parent reference onto the live parent field when the
        // reloaded view description provides it (same move as the group-value
        // re-aliasing in `sectionsFromState`).
        const parent = target.searchViewFields[copy.relatedPropertyField?.name];
        if (parent) {
            copy.relatedPropertyField = parent;
        }
        target.searchViewFields[name] = copy;
    }
}

/**
 * @param {Record<string, any>} globalContext
 * @returns {{ searchDefaults: Object, searchPanelDefaults: Object }}
 */
export function extractSearchDefaults(globalContext) {
    /** @type {Record<string, any>} */
    const searchDefaults = {};
    /** @type {Record<string, any>} */
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
