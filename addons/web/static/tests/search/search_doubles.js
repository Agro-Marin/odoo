// @ts-check

import { Mutex } from "@web/core/utils/concurrency";

/**
 * Test doubles for the `SearchModel` mixin composition, one per unit, each
 * covering everything that unit's contract says it reaches.
 *
 * WHY THIS FILE EXISTS
 * --------------------
 *
 * Every mixin suite used to build its own double inline -- `Object.assign(new
 * Mixin(class {})(), { searchItems: {}, query: [], nextId: 1, blockNotification:
 * false, _notify() {…} })` -- and three of them wrote overlapping halves of the
 * same substrate. Nothing checked any of them against the composition. A double
 * that has fallen behind does not fail: the missing member reads `undefined`,
 * the assertion under test still passes, and the suite goes green against a
 * fiction. `search_panel_mixin.test.js` covered **5** of the 19 names its unit
 * declares.
 *
 * `model/relational_model/` answers this with `record_doubles.js` plus
 * `record_doubles_conformance.test.js`, and this is the same pair:
 * `search_doubles_conformance.test.js` fails when a double stops covering its
 * contract, and `js_mixin_coupling --check` fails when the contract stops
 * covering the code. The two together mean a mixin cannot grow a reach without
 * something going red.
 *
 * The members are written out rather than generated from the contract on
 * purpose. A double derived from the declaration would satisfy any check
 * against that declaration by construction, which is a test that cannot fail.
 */

/** @import { QueryElement } from "@web/search/search_types" */

/**
 * Members the doubles add for the tests' own benefit, declared by no unit.
 * The conformance test permits exactly these and nothing else.
 *
 * @type {string[]}
 */
export const DOUBLE_ONLY_MEMBERS = ["_notifications"];

/**
 * The notification channel every unit ends a mutation with, plus the block
 * window two of them wrap writes in. Shared because the real composition
 * shares it -- `_notify` is reached by five of the six units.
 *
 * @param {string[]} steps
 */
function notificationChannel(steps) {
    return {
        blockNotification: false,
        _notifications: steps,
        /** @this {any} */
        _notify() {
            if (this.blockNotification) {
                return;
            }
            steps.push("notify");
        },
        /**
         * @this {any}
         * @param {() => void} fn
         */
        _withNotificationsBlocked(fn) {
            const wasBlocked = this.blockNotification;
            this.blockNotification = true;
            try {
                fn();
            } finally {
                this.blockNotification = wasBlocked;
            }
        },
    };
}

/**
 * The item registry and the query the registry is indexed against: the state
 * assigned in `SearchModel.setup()` that four units read straight off `this`.
 */
function itemRegistry() {
    return {
        /** @type {Record<number, any>} */
        searchItems: {},
        /** @type {QueryElement[]} */
        query: [],
        nextId: 1,
        nextGroupId: 1,
        nextGroupNumber: 1,
        searchViewFields: {},
        resModel: "partner",
        globalContext: {},
    };
}

/**
 * The derivation family the mixins call up into. Answers are inert by design:
 * a suite that cares about one of them overrides it, and a suite that does not
 * should not be silently depending on its shape.
 */
function derivations() {
    return {
        _getContext: () => ({}),
        _getDomain: () => /** @type {any[]} */ ([]),
        _getGroupBy: () => /** @type {any[]} */ ([]),
        _getOrderBy: () => /** @type {any[]} */ ([]),
        _getGroups: () => /** @type {any[]} */ ([]),
        _getCategoryDomain: () => /** @type {any[]} */ ([]),
        _getFilterDomain: () => /** @type {any[]} */ ([]),
        _getGroupDomain: () => /** @type {any[]} */ ([]),
        _getSearchItemContext: () => ({}),
        _getSearchItemGroupBys: () => /** @type {any[]} */ ([]),
        _rawContext: {},
        /** @type {any[] | null} */
        _enrichedSearchItems: null,
        isDebugMode: false,
    };
}

/** @type {Record<string, (steps: string[]) => Record<string, any>>} */
const DOUBLES = {
    "search/search_favorites_mixin.js": (steps) => ({
        ...notificationChannel(steps),
        ...itemRegistry(),
        _createGroupOfSearchItems: () => {},
        _getContext: () => ({}),
        _getDomain: () => /** @type {any[]} */ ([]),
        _getGroupBy: () => /** @type {any[]} */ ([]),
        _getOrderBy: () => /** @type {any[]} */ ([]),
        /** @this {any} */
        clearQuery() {
            this.query = [];
        },
        /** @type {any[] | null} */
        _enrichedSearchItems: null,
        env: {},
        orm: {},
        irFilters: [],
    }),

    "search/search_query_mixin.js": (steps) => ({
        ...notificationChannel(steps),
        ...itemRegistry(),
        /**
         * @this {any}
         * @param {number} searchItemId
         */
        _getSelectedGeneratorIds(searchItemId) {
            return this.query
                .filter(
                    (/** @type {any} */ q) =>
                        q.searchItemId === searchItemId && "generatorId" in q,
                )
                .map((/** @type {any} */ q) => q.generatorId);
        },
        defaultGroupBy: undefined,
        defaultGroupByRemoved: false,
        globalGroupBy: [],
        orderByCount: false,
        referenceMoment: null,
    }),

    "search/search_panel/search_panel_mixin.js": (steps) => ({
        ...notificationChannel(steps),
        _getCategoryDomain: () => /** @type {any[]} */ ([]),
        _getDomain: () => /** @type {any[]} */ ([]),
        _getFilterDomain: () => /** @type {any[]} */ ([]),
        _getGroupDomain: () => /** @type {any[]} */ ([]),
        categories: [],
        filters: [],
        _reloadMutex: new Mutex(),
        /** @type {Set<number>} */
        _sectionLoadIds: new Set(),
        _sections: null,
        display: { searchPanel: true },
        globalContext: {},
        orm: {},
        resModel: "partner",
        searchDomain: [],
        searchPanelInfo: { loaded: false, shouldReload: false },
        /** @type {Map<number, any>} */
        sections: new Map(),
        sectionsPromise: null,
    }),

    "search/search_properties_mixin.js": (steps) => ({
        ...notificationChannel(steps),
        ...itemRegistry(),
        _rawContext: {},
        getSearchItems: () => /** @type {any[]} */ ([]),
        /** @type {any[] | null} */
        _enrichedSearchItems: null,
        _filledPropertyFields: new Set(),
        fieldService: {},
    }),

    "search/search_split_domain_mixin.js": (steps) => ({
        ...notificationChannel(steps),
        ...itemRegistry(),
        ...derivations(),
        createNewFilters: () => {},
        createNewGroupBy: () => {},
        deactivateGroup: () => {},
        fillSearchViewItemsProperty: () => {},
        defaultGroupBy: undefined,
        env: {},
        treeProcessor: {},
        DomainSelectorDialog: class {},
        dialog: {},
        getDefaultDomain: () => /** @type {any[]} */ ([]),
    }),
};

/**
 * The members one unit's double supplies, before overrides.
 *
 * @param {string} module
 * @returns {Record<string, any>}
 */
export function doubleMembersFor(module) {
    const build = DOUBLES[module];
    if (!build) {
        throw new Error(`no double declared for ${module}`);
    }
    return build([]);
}

/**
 * A double for one unit of the composition, ready to be assigned onto an
 * instance of that unit's mixin applied to a bare class.
 *
 * @param {string} module — the unit's path, as SEARCH_COMPOSITION_ORDER spells it
 * @param {Record<string, any>} [overrides]
 * @returns {any}
 */
export function makeCompositionDouble(module, overrides = {}) {
    const build = DOUBLES[module];
    if (!build) {
        throw new Error(`no double declared for ${module}`);
    }
    /** @type {string[]} */
    const steps = [];
    return { ...build(steps), ...overrides };
}
