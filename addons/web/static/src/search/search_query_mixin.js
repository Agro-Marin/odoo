// @ts-check
/** @odoo-module native */

/** @module @web/search/search_query_mixin - Query mutation methods mixed into SearchModel */

import { _t } from "@web/core/l10n/translation";

import { SPECIAL } from "./search_state.js";
import { DEFAULT_INTERVAL, getPeriodOptions, yearSelected } from "./utils/dates.js";

/**
 * Query mutation methods for SearchModel: activating/deactivating filters,
 * group-bys and date filters, creating custom filters/group-bys/favorites entry
 * points, and clearing the query.
 *
 * Mixed into SearchModel (``extends SearchQueryMixin(...)``) rather than kept as
 * pass-``this`` module functions with thin proxy methods: the logic now lives on
 * the prototype directly, using ``this`` (no owner argument, no proxy round-trip).
 * None of these methods is overridden by any SearchModel subclass, so folding
 * them in is behaviour-preserving. ``query``/``searchItems``/``nextId`` state and
 * the domain/facet getters live on SearchModel and are reached via ``this``.
 *
 * The mutators that used to return nothing now return ``_notify()``'s promise,
 * which settles once the search panel has reloaded and the UPDATE event has
 * fired. Purely additive — nothing read the old ``undefined`` — and it means a
 * caller (a test, a controller sequencing two mutations) can await the settled
 * state instead of guessing at ticks.
 *
 * @template {new (...args: any[]) => any} T
 * @param {T} Base
 */
export const SearchQueryMixin = (Base) =>
    class extends Base {
        /**
         * Deactivate the order-by-count flag when no EFFECTIVE groupBy remains.
         *
         * An effective groupBy is either an active query groupBy/dateGroupBy OR a
         * surviving ``defaultGroupBy`` fallback (which computeGroupBy still injects,
         * and which computeOrderBy still count-sorts). Scanning only ``query``
         * dropped the user's count sort whenever an unrelated filter was toggled
         * off while the sole group-by present was the SPECIAL default-group-by facet.
         */
        _checkOrderByCountStatus() {
            if (!this.orderByCount) {
                return;
            }
            const hasQueryGroupBy = this.query.some((item) =>
                ["dateGroupBy", "groupBy"].includes(
                    this.searchItems[item.searchItemId].type,
                ),
            );
            const hasDefaultGroupBy = Boolean(this.defaultGroupBy?.length);
            if (!hasQueryGroupBy && !hasDefaultGroupBy) {
                this.orderByCount = false;
            }
        }

        /**
         * Run ``fn`` with search-model notifications blocked, restoring the previous
         * ``blockNotification`` state afterwards — even if ``fn`` throws, and even
         * when nested inside another blocked window (e.g. splitAndAddDomain →
         * createNewGroupBy).
         *
         * @param {() => void} fn - synchronous callback run inside the blocked window
         */
        _withNotificationsBlocked(fn) {
            const wasBlocked = this.blockNotification;
            this.blockNotification = true;
            try {
                fn();
            } finally {
                this.blockNotification = wasBlocked;
            }
        }

        /**
         * Activate a filter of type 'field' with given searchItemId with
         * autocomplete value, label, and operator.
         * @param {number} searchItemId
         * @param {Object} autocompleteValue
         */
        addAutoCompletionValues(searchItemId, autocompleteValue) {
            const searchItem = this.searchItems[searchItemId];
            if (!["field", "field_property"].includes(searchItem.type)) {
                return;
            }
            const { label, value, operator } = autocompleteValue;
            const queryElem = this.query.find(
                (queryElem) =>
                    queryElem.searchItemId === searchItemId &&
                    "autocompleteValue" in queryElem &&
                    queryElem.autocompleteValue.value === value &&
                    queryElem.autocompleteValue.operator === operator,
            );
            if (!queryElem) {
                this.query.push({ searchItemId, autocompleteValue });
            } else {
                queryElem.autocompleteValue.label = label;
            }
            return this._notify();
        }

        /** Remove all query elements. */
        clearQuery() {
            this.query = [];
            this.orderByCount = false;
            return this._notify();
        }

        /**
         * Create new search items of type 'filter' and activate them.
         * @param {Object[]} prefilters
         * @returns {number[]} ids of the created search items
         */
        createNewFilters(prefilters) {
            if (!prefilters.length) {
                return [];
            }
            const searchItemIds = [];
            prefilters.forEach((preFilter) => {
                const filter = {
                    ...preFilter,
                    groupId: this.nextGroupId,
                    groupNumber: this.nextGroupNumber,
                    id: this.nextId,
                    type: "filter",
                };
                this.searchItems[this.nextId] = filter;
                this.query.push({ searchItemId: this.nextId });
                searchItemIds.push(this.nextId);
                this.nextId++;
            });
            this.nextGroupId++;
            this.nextGroupNumber++;
            this._notify();
            return searchItemIds;
        }

        /**
         * Create a new filter of type 'groupBy' or 'dateGroupBy' and activate it.
         * @param {string} fieldName
         * @param {Object} [options]
         * @param {string} [options.interval]
         * @param {boolean} [options.invisible]
         * @returns {number} id of the created search item
         */
        createNewGroupBy(fieldName, { interval, invisible } = {}) {
            const field = this.searchViewFields[fieldName];
            const { string, type: fieldType } = field;
            const firstGroupBy = Object.values(this.searchItems).find(
                (f) => f.type === "groupBy" || f.type === "dateGroupBy",
            );
            const preSearchItem = {
                description: string || fieldName,
                fieldName,
                fieldType,
                groupId: firstGroupBy ? firstGroupBy.groupId : this.nextGroupId++,
                groupNumber: this.nextGroupNumber,
                id: this.nextId,
                custom: true,
            };
            if (invisible) {
                preSearchItem.invisible = "True";
            }
            this._withNotificationsBlocked(() => {
                if (["date", "datetime"].includes(fieldType)) {
                    this.searchItems[this.nextId] = Object.assign(
                        {
                            type: "dateGroupBy",
                            defaultIntervalId: interval || DEFAULT_INTERVAL,
                        },
                        preSearchItem,
                    );
                    this.toggleDateGroupBy(this.nextId);
                } else {
                    this.searchItems[this.nextId] = Object.assign(
                        { type: "groupBy" },
                        preSearchItem,
                    );
                    this.toggleSearchItem(this.nextId);
                }
                this.nextGroupNumber++;
                this.nextId++;
            });
            this._notify();
            return preSearchItem.id;
        }

        /**
         * Deactivate a group, i.e. delete the query elements with given groupId.
         * @param {number|symbol} groupId
         */
        deactivateGroup(groupId) {
            if (groupId === SPECIAL) {
                delete this.defaultGroupBy;
                this.defaultGroupByRemoved = true;
                this._checkOrderByCountStatus();
                return this._notify();
            }
            this.query = this.query.filter((queryElem) => {
                const searchItem = this.searchItems[queryElem.searchItemId];
                return searchItem.groupId !== groupId;
            });
            this._checkOrderByCountStatus();
            return this._notify();
        }

        /**
         * Toggle a simple filter on or off.
         * @param {number} searchItemId
         */
        toggleSearchItem(searchItemId) {
            const searchItem = this.searchItems[searchItemId];
            if (searchItem.isInvalid) {
                return;
            }
            switch (searchItem.type) {
                case "dateFilter":
                case "dateGroupBy":
                case "field_property":
                case "field": {
                    return;
                }
            }
            const index = this.query.findIndex(
                (queryElem) => queryElem.searchItemId === searchItemId,
            );
            if (index >= 0) {
                this.query.splice(index, 1);
                this._checkOrderByCountStatus();
            } else {
                if (searchItem.type === "favorite") {
                    this.query = [];
                    this.orderByCount = false;
                }
                this.query.push({ searchItemId });
            }
            return this._notify();
        }

        /**
         * Toggle a date filter query element.
         * @param {number} searchItemId
         * @param {string} [generatorId]
         */
        toggleDateFilter(searchItemId, generatorId) {
            const searchItem = this.searchItems[searchItemId];
            if (searchItem.type !== "dateFilter") {
                return;
            }
            let generatorIds = generatorId
                ? [generatorId]
                : searchItem.defaultGeneratorIds;
            const knownOptions = searchItem.optionsParams
                ? getPeriodOptions(this.referenceMoment, searchItem.optionsParams)
                : null;
            if (knownOptions) {
                const validGeneratorIds = generatorIds.filter(
                    (gid) =>
                        gid.startsWith("custom") ||
                        knownOptions.some((o) => o.id === gid),
                );
                if (validGeneratorIds.length !== generatorIds.length) {
                    console.warn(
                        `[search] unknown period generator id(s) on filter "${searchItem.name}":`,
                        generatorIds.filter((gid) => !validGeneratorIds.includes(gid)),
                    );
                }
                generatorIds = validGeneratorIds;
            }
            // Selecting a custom period replaces whatever the filter held, so a
            // multi-custom default (`default_period`/`search_default_*` naming
            // several) resolves to its last entry alone. Say so rather than
            // dropping the others without a trace.
            const customIds = generatorIds.filter((gid) => gid.startsWith("custom"));
            if (customIds.length > 1) {
                console.warn(
                    `[search] date filter "${searchItem.name}": custom periods are mutually exclusive; ` +
                        `keeping "${customIds.at(-1)}" and ignoring`,
                    customIds.slice(0, -1),
                );
            }
            for (const generatorId of generatorIds) {
                const index = this.query.findIndex(
                    (queryElem) =>
                        queryElem.searchItemId === searchItemId &&
                        "generatorId" in queryElem &&
                        queryElem.generatorId === generatorId,
                );
                if (index >= 0) {
                    this.query.splice(index, 1);
                    if (!yearSelected(this._getSelectedGeneratorIds(searchItemId))) {
                        this.query = this.query.filter(
                            (queryElem) => queryElem.searchItemId !== searchItemId,
                        );
                    }
                } else {
                    if (generatorId.startsWith("custom")) {
                        this.query = this.query.filter(
                            (queryElem) => searchItemId !== queryElem.searchItemId,
                        );
                        this.query.push({ searchItemId, generatorId });
                        continue;
                    }
                    this.query = this.query.filter(
                        (queryElem) =>
                            queryElem.searchItemId !== searchItemId ||
                            !queryElem.generatorId.startsWith("custom"),
                    );
                    this.query.push({ searchItemId, generatorId });
                    if (
                        knownOptions &&
                        !yearSelected(this._getSelectedGeneratorIds(searchItemId))
                    ) {
                        const periodOption = knownOptions.find(
                            (o) => o.id === generatorId,
                        );
                        if (!periodOption) {
                            break;
                        }
                        const { defaultYearId } = periodOption;
                        this.query.push({
                            searchItemId,
                            generatorId: defaultYearId,
                        });
                    }
                }
            }
            return this._notify();
        }

        /**
         * Toggle a date groupBy interval.
         * @param {number} searchItemId
         * @param {string} [intervalId]
         */
        toggleDateGroupBy(searchItemId, intervalId) {
            const searchItem = this.searchItems[searchItemId];
            if (searchItem.type !== "dateGroupBy") {
                return;
            }
            intervalId = intervalId || searchItem.defaultIntervalId;
            const index = this.query.findIndex(
                (queryElem) =>
                    queryElem.searchItemId === searchItemId &&
                    "intervalId" in queryElem &&
                    queryElem.intervalId === intervalId,
            );
            if (index >= 0) {
                this.query.splice(index, 1);
                this._checkOrderByCountStatus();
            } else {
                this.query.push({ searchItemId, intervalId });
            }
            return this._notify();
        }

        /** Open the custom filter dialog (DomainSelectorDialog). */
        async spawnCustomFilterDialog() {
            const domain = this.getDefaultDomain(this.searchViewFields);
            this.dialog.add(this.DomainSelectorDialog, {
                resModel: this.resModel,
                defaultConnector: "|",
                domain,
                context: this.globalContext,
                onConfirm: (domain) => this.splitAndAddDomain(domain),
                disableConfirmButton: (domain) => domain === `[]`,
                title: _t("Custom Filter"),
                confirmButtonText: _t("Search"),
                discardButtonText: _t("Discard"),
                isDebugMode: this.isDebugMode,
            });
        }

        /** Toggle groupBy sort direction between Desc/Asc. */
        switchGroupBySort() {
            if (this.orderByCount === "Desc") {
                this.orderByCount = "Asc";
            } else {
                this.orderByCount = "Desc";
            }
            return this._notify();
        }
    };
