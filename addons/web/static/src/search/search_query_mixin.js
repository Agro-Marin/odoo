// @ts-check
/** @odoo-module native */

import { _t } from "@web/core/translation";

import { findGroupByGroupId } from "./search_group_by.js";
import { fireAndForgetNotify } from "./search_notification.js";
import { SPECIAL } from "./search_state.js";
import { DEFAULT_INTERVAL, getPeriodOptions, yearSelected } from "./utils/dates.js";

/**
 * @template {new (...args: any[]) => any} T
 * @param {T} Base
 */
export const SearchQueryMixin = (Base) =>
    class extends Base {
        /** @this {any} */
        _checkOrderByCountStatus() {
            if (!this.orderByCount) {
                return;
            }
            const hasQueryGroupBy = this.query.some((/** @type {any} */ item) =>
                ["dateGroupBy", "groupBy"].includes(
                    this.searchItems[item.searchItemId].type,
                ),
            );
            const hasGlobalGroupBy = Boolean(this.globalGroupBy?.length);
            const hasDefaultGroupBy = Boolean(this.defaultGroupBy?.length);
            if (!hasQueryGroupBy && !hasGlobalGroupBy && !hasDefaultGroupBy) {
                this.orderByCount = /** @type {string|false} */ (false);
            }
        }

        /**
         * @param {() => void} fn
         */
        _withNotificationsBlocked(fn) {
            const wasBlocked = /** @type {boolean} */ (this.blockNotification);
            this.blockNotification = /** @type {boolean} */ (true);
            try {
                fn();
            } finally {
                this.blockNotification = /** @type {boolean} */ (wasBlocked);
            }
        }

        /**
         * @param {number} searchItemId
         * @param {Record<string, any>} autocompleteValue
         */
        async addAutoCompletionValues(searchItemId, autocompleteValue) {
            const searchItem = this.searchItems[searchItemId];
            if (!["field", "field_property"].includes(searchItem.type)) {
                return;
            }
            const { label, value, operator } = autocompleteValue;
            const queryElem = this.query.find(
                (/** @type {any} */ queryElem) =>
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

        async clearQuery() {
            this.query = /** @type {any[]} */ ([]);
            this.orderByCount = /** @type {string|false} */ (false);
            return this._notify();
        }

        /**
         * @param {Record<string, any>[]} prefilters
         * @returns {number[]}
         */
        createNewFilters(prefilters) {
            if (!prefilters.length) {
                return [];
            }
            /** @type {number[]} */
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
            fireAndForgetNotify(this._notify());
            return searchItemIds;
        }

        /**
         * @param {string} fieldName
         * @param {object} [options]
         * @param {string} [options.interval]
         * @param {boolean} [options.invisible]
         * @returns {number | undefined}
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
            /** @type {Record<string, any>} */
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
            fireAndForgetNotify(this._notify());
            return preSearchItem.id;
        }

        /**
         * @param {number|symbol} groupId
         */
        async deactivateGroup(groupId) {
            if (groupId === SPECIAL) {
                delete this.defaultGroupBy;
                this.defaultGroupByRemoved = true;
                this._checkOrderByCountStatus();
                return this._notify();
            }
            this.query = this.query.filter((/** @type {any} */ queryElem) => {
                const searchItem = this.searchItems[queryElem.searchItemId];
                return searchItem.groupId !== groupId;
            });
            this._checkOrderByCountStatus();
            return this._notify();
        }

        /**
         * @param {number} searchItemId
         */
        async toggleSearchItem(searchItemId) {
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
                (/** @type {any} */ queryElem) =>
                    queryElem.searchItemId === searchItemId,
            );
            if (index >= 0) {
                this.query.splice(index, 1);
                this._checkOrderByCountStatus();
            } else {
                if (searchItem.type === "favorite") {
                    this.query = /** @type {any[]} */ ([]);
                    this.orderByCount = /** @type {string|false} */ (false);
                }
                this.query.push({ searchItemId });
            }
            return this._notify();
        }

        /**
         * @param {any} searchItem
         * @param {string} [generatorId]
         * @param {readonly any[] | null} [knownOptions]
         * @returns {string[]}
         */
        _resolveDateGeneratorIds(searchItem, generatorId, knownOptions) {
            let generatorIds = generatorId
                ? [generatorId]
                : searchItem.defaultGeneratorIds;
            if (knownOptions) {
                const validGeneratorIds = generatorIds.filter(
                    (/** @type {any} */ gid) =>
                        gid.startsWith("custom") ||
                        knownOptions.some((o) => o.id === gid),
                );
                if (validGeneratorIds.length !== generatorIds.length) {
                    console.warn(
                        `[search] unknown period generator id(s) on filter "${searchItem.name}":`,
                        generatorIds.filter(
                            (/** @type {any} */ gid) =>
                                !validGeneratorIds.includes(gid),
                        ),
                    );
                }
                generatorIds = validGeneratorIds;
            }
            const customIds = generatorIds.filter((/** @type {any} */ gid) =>
                gid.startsWith("custom"),
            );
            if (customIds.length > 1) {
                console.warn(
                    `[search] date filter "${searchItem.name}": custom periods are mutually exclusive; ` +
                        `keeping "${customIds.at(-1)}" and ignoring`,
                    customIds.slice(0, -1),
                );
            }
            return generatorIds;
        }

        /**
         * @param {number} searchItemId
         * @param {string} [generatorId]
         */
        async toggleDateFilter(searchItemId, generatorId) {
            const searchItem = this.searchItems[searchItemId];
            if (searchItem.type !== "dateFilter") {
                return;
            }
            const knownOptions = searchItem.optionsParams
                ? getPeriodOptions(this.referenceMoment, searchItem.optionsParams)
                : null;
            const generatorIds = this._resolveDateGeneratorIds(
                searchItem,
                generatorId,
                knownOptions,
            );
            for (const generatorId of generatorIds) {
                const index = this.query.findIndex(
                    (/** @type {any} */ queryElem) =>
                        queryElem.searchItemId === searchItemId &&
                        "generatorId" in queryElem &&
                        queryElem.generatorId === generatorId,
                );
                if (index >= 0) {
                    this.query.splice(index, 1);
                    if (!yearSelected(this._getSelectedGeneratorIds(searchItemId))) {
                        this.query = this.query.filter(
                            (/** @type {any} */ queryElem) =>
                                queryElem.searchItemId !== searchItemId,
                        );
                    }
                } else {
                    if (generatorId.startsWith("custom")) {
                        this.query = this.query.filter(
                            (/** @type {any} */ queryElem) =>
                                searchItemId !== queryElem.searchItemId,
                        );
                        this.query.push({ searchItemId, generatorId });
                        continue;
                    }
                    this.query = this.query.filter(
                        (/** @type {any} */ queryElem) =>
                            queryElem.searchItemId !== searchItemId ||
                            !queryElem.generatorId.startsWith("custom"),
                    );
                    this.query.push({ searchItemId, generatorId });
                    if (
                        knownOptions &&
                        !yearSelected(this._getSelectedGeneratorIds(searchItemId))
                    ) {
                        const knownOption = knownOptions.find(
                            (o) => o.id === generatorId,
                        );
                        if (knownOption) {
                            this.query.push({
                                searchItemId,
                                generatorId: knownOption.defaultYearId,
                            });
                        }
                    }
                }
            }
            return this._notify();
        }

        /**
         * @param {number} searchItemId
         * @param {string} [intervalId]
         */
        async toggleDateGroupBy(searchItemId, intervalId) {
            const searchItem = this.searchItems[searchItemId];
            if (searchItem.type !== "dateGroupBy") {
                return;
            }
            intervalId = intervalId || searchItem.defaultIntervalId;
            const index = this.query.findIndex(
                (/** @type {any} */ queryElem) =>
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
                onConfirm: (/** @type {any} */ domain) =>
                    this.splitAndAddDomain(domain),
                disableConfirmButton: (/** @type {any} */ domain) => domain === `[]`,
                title: _t("Custom Filter"),
                confirmButtonText: _t("Search"),
                discardButtonText: _t("Discard"),
                isDebugMode: this.isDebugMode,
            });
        }

        async switchGroupBySort() {
            if (this.orderByCount === "Desc") {
                this.orderByCount = "Asc";
            } else {
                this.orderByCount = "Desc";
            }
            return this._notify();
        }
    };
