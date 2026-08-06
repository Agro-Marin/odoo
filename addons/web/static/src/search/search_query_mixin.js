// @ts-check
/** @odoo-module native */

/** @module @web/search/search_query_mixin */

import { _t } from "@web/core/translation";

import { findGroupByGroupId } from "./search_group_by.js";
import { SPECIAL } from "./search_state.js";
import { DEFAULT_INTERVAL, getPeriodOptions, yearSelected } from "./utils/dates.js";

/**
 * @template {new (...args: any[]) => any} T
 * @param {T} Base
 */
export const SearchQueryMixin = (Base) =>
    class extends Base {
        _checkOrderByCountStatus() {
            if (!this.orderByCount) {
                return;
            }
            const hasQueryGroupBy = this.query.some((item) =>
                ["dateGroupBy", "groupBy"].includes(
                    this.searchItems[item.searchItemId].type,
                ),
            );
            // `computeGroupBy` falls back on the config-level group-by
            // (`globalGroupBy`) before `defaultGroupBy`, so grouping -- and
            // with it a meaningful count order -- survives an empty query.
            const hasGlobalGroupBy = Boolean(this.globalGroupBy?.length);
            const hasDefaultGroupBy = Boolean(this.defaultGroupBy?.length);
            if (!hasQueryGroupBy && !hasGlobalGroupBy && !hasDefaultGroupBy) {
                this.orderByCount = false;
            }
        }

        /**
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
        }

        /**
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

        clearQuery() {
            this.query = [];
            this.orderByCount = false;
            return this._notify();
        }

        /**
         * @param {Object[]} prefilters
         * @returns {number[]}
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
         * @param {string} fieldName
         * @param {Object} [options]
         * @param {string} [options.interval]
         * @param {boolean} [options.invisible]
         * @returns {number | undefined} `undefined` when `fieldName` is not in the search view
         */
        createNewGroupBy(fieldName, { interval, invisible } = {}) {
            const field = this.searchViewFields[fieldName];
            if (!field) {
                console.warn(
                    `[search] ignoring group-by on unknown field "${fieldName}"`,
                );
                return undefined;
            }
            const { string, type: fieldType } = field;
            const preSearchItem = {
                description: string || fieldName,
                fieldName,
                fieldType,
                groupId: findGroupByGroupId(this.searchItems) ?? this.nextGroupId++,
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
                        const { defaultYearId } = knownOptions.find(
                            (o) => o.id === generatorId,
                        );
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

        switchGroupBySort() {
            if (this.orderByCount === "Desc") {
                this.orderByCount = "Asc";
            } else {
                this.orderByCount = "Desc";
            }
            return this._notify();
        }
    };
