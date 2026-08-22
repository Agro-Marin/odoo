// @ts-check
/** @odoo-module native */

import { makeContext } from "@web/core/context";
import { domainFromTree } from "@web/core/tree/domain_from_tree";

/**
 * @template {new (...args: any[]) => any} T
 * @param {T} Base
 */
export const SearchSplitDomainMixin = (Base) =>
    class extends Base {
        /**
         * @param {Record<string, any>} group
         * @returns {Record<string, any>}
         */
        _mergedContextOfGroup(group) {
            const contexts = [];
            for (const activeItem of group.activeItems) {
                const ctx = this._getSearchItemContext(activeItem);
                if (ctx) {
                    contexts.push(ctx);
                }
            }
            return makeContext(contexts);
        }

        /**
         * @param {string} domain
         * @param {Record<string, any>} [context]
         * @returns {Promise<Object[]>}
         */
        async _domainToPreFilters(domain, context) {
            const tree = await this.treeProcessor.treeFromDomain(
                this.resModel,
                domain,
                !this.isDebugMode,
            );
            const trees =
                !tree.negate &&
                tree.type === "connector" &&
                tree.value === "&" &&
                tree.children.length
                    ? tree.children
                    : [tree];
            return Promise.all(
                trees.map(async (/** @type {any} */ tree) => {
                    const [description, tooltip] = await Promise.all([
                        this.treeProcessor.getDomainTreeDescription(
                            this.resModel,
                            tree,
                        ),
                        this.treeProcessor.getDomainTreeTooltip(this.resModel, tree),
                    ]);
                    /** @type {Record<string, any>} */
                    const preFilter = {
                        description,
                        tooltip,
                        domain: domainFromTree(tree),
                        invisible: "True",
                        type: "filter",
                    };
                    if (context) {
                        preFilter.context = context;
                    }
                    return preFilter;
                }),
            );
        }

        /**
         * @param {Record<string, any>} group
         * @returns {Record<string, any>|undefined}
         */
        _firstSearchItemOf(group) {
            return this.searchItems[group.activeItems[0]?.searchItemId];
        }

        /**
         * @param {Record<string, any>} group
         * @returns {Promise<void>}
         */
        async _ensurePropertyFieldsForFavorite(group) {
            if (this._firstSearchItemOf(group)?.type !== "favorite") {
                return;
            }
            const groupBys = this._getSearchItemGroupBys(group.activeItems[0]) || [];
            const needsPropertyFields = groupBys.some((/** @type {any} */ groupBy) =>
                groupBy.split(":")[0].includes("."),
            );
            if (needsPropertyFields) {
                await this.fillSearchViewItemsProperty();
            }
        }

        /**
         * @param {Record<string, any>} group
         * @returns {number[]}
         */
        _carryOverFavoriteGroupBys(group) {
            if (this._firstSearchItemOf(group)?.type !== "favorite") {
                return [];
            }
            const activeItemGroupBys = this._getSearchItemGroupBys(
                group.activeItems[0],
            );
            if (!activeItemGroupBys.length) {
                return [];
            }
            if (this.defaultGroupBy && this.env.config.viewType === "kanban") {
                const currentGroupBy = this._getGroupBy({ fallbackOnDefault: false });
                if (
                    JSON.stringify(currentGroupBy) ===
                    JSON.stringify(this.defaultGroupBy)
                ) {
                    return [];
                }
            }
            /** @type {number[]} */
            const newGroupByIds = [];
            for (const activeItemGroupBy of activeItemGroupBys) {
                const [fieldName, interval] = activeItemGroupBy.split(":");
                const newGroupById = this.createNewGroupBy(fieldName, {
                    interval,
                    invisible: true,
                });
                if (newGroupById !== undefined) {
                    newGroupByIds.push(newGroupById);
                }
            }
            const isNewGroupBy = (/** @type {any} */ queryElem) =>
                newGroupByIds.includes(queryElem.searchItemId);
            this.query = /** @type {any[]} */ ([
                ...this.query.filter(isNewGroupBy),
                ...this.query.filter(
                    (/** @type {any} */ queryElem) => !isNewGroupBy(queryElem),
                ),
            ]);
            return newGroupByIds;
        }

        /**
         * @param {number[]} newFilterIds
         * @param {Record<string, any>|null} anchor
         */
        _moveQueryElemsAfter(newFilterIds, anchor) {
            const isNewFilter = (/** @type {any} */ queryElem) =>
                newFilterIds.includes(queryElem.searchItemId);
            /** @type {any[]} */
            const newQueryElems = this.query.filter(isNewFilter);
            /** @type {any[]} */
            const otherQueryElems = this.query.filter(
                (/** @type {any} */ queryElem) => !isNewFilter(queryElem),
            );
            const anchorIndex = anchor ? otherQueryElems.indexOf(anchor) : -1;
            const at = anchorIndex + 1;
            this.query = [
                ...otherQueryElems.slice(0, at),
                ...newQueryElems,
                ...otherQueryElems.slice(at),
            ];
        }

        /**
         * @param {string} domain
         * @param {number} [groupId]
         */
        async splitAndAddDomain(domain, groupId) {
            const group = groupId
                ? this._getGroups().find((/** @type {any} */ g) => g.id === groupId)
                : null;
            const context = group ? this._mergedContextOfGroup(group) : undefined;
            const preFilters = await this._domainToPreFilters(domain, context);
            if (group) {
                await this._ensurePropertyFieldsForFavorite(group);
            }

            this._withNotificationsBlocked(() => {
                let anchor = null;
                if (group) {
                    const replacedIndex = this.query.findIndex(
                        (/** @type {any} */ queryElem) =>
                            queryElem.searchItemId ===
                            group.activeItems[0].searchItemId,
                    );
                    if (replacedIndex > 0) {
                        anchor = this.query[replacedIndex - 1];
                    }
                    this._carryOverFavoriteGroupBys(group);
                    this.deactivateGroup(groupId);
                }

                const newFilterIds = preFilters.flatMap((preFilter) =>
                    this.createNewFilters([preFilter]),
                );

                if (group) {
                    this._moveQueryElemsAfter(newFilterIds, anchor);
                }
            });

            await this._notify();
        }
    };
