// @ts-check

import { Mutex } from "@web/core/utils/concurrency";

/** @type {string[]} */
export const DOUBLE_ONLY_MEMBERS = ["_notifications"];

/** @param {string[]} steps */
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
                return fn();
            } finally {
                this.blockNotification = wasBlocked;
            }
        },
        /**
         * @this {any}
         * @param {() => Promise<any>} fn
         */
        async _withNotificationsBlockedAsync(fn) {
            const wasBlocked = this.blockNotification;
            this.blockNotification = true;
            try {
                return await fn();
            } finally {
                this.blockNotification = wasBlocked;
            }
        },
    };
}

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
        /** @type {any[] | null} */
        _enrichedSearchItems: null,
        domainEvalContext: {},
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
 * @param {string} module
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
