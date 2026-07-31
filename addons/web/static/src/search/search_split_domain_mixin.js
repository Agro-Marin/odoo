// @ts-check
/** @odoo-module native */

/** @module @web/search/search_split_domain_mixin */

import { makeContext } from "@web/core/context";
import { domainFromTree } from "@web/core/tree/domain_from_tree";

/**
 * @template {new (...args: any[]) => any} T
 * @param {T} Base
 */
export const SearchSplitDomainMixin = (Base) =>
    class extends Base {
        /**
         * @param {string} domain
         * @param {number} [groupId]
         */
        async splitAndAddDomain(domain, groupId) {
            const group = groupId
                ? this._getGroups().find((g) => g.id === groupId)
                : null;
            let context;
            if (group) {
                const contexts = [];
                for (const activeItem of group.activeItems) {
                    const ctx = this._getSearchItemContext(activeItem);
                    if (ctx) {
                        contexts.push(ctx);
                    }
                }
                context = makeContext(contexts);
            }

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
            const promises = trees.map(async (tree) => {
                const [description, tooltip] = await Promise.all([
                    this.treeProcessor.getDomainTreeDescription(this.resModel, tree),
                    this.treeProcessor.getDomainTreeTooltip(this.resModel, tree),
                ]);
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
            });

            const preFilters = await Promise.all(promises);

            if (group) {
                const firstActiveItem = group.activeItems[0];
                const firstSearchItem = this.searchItems[firstActiveItem.searchItemId];
                if (firstSearchItem.type === "favorite") {
                    const groupBys = this._getSearchItemGroupBys(firstActiveItem) || [];
                    const needsPropertyFields = groupBys.some((groupBy) =>
                        groupBy.split(":")[0].includes("."),
                    );
                    if (needsPropertyFields) {
                        await this.fillSearchViewItemsProperty();
                    }
                }
            }

            this._withNotificationsBlocked(() => {
                let queryItemIndex;
                if (group) {
                    const firstActiveItem = group.activeItems[0];
                    const firstSearchItem =
                        this.searchItems[firstActiveItem.searchItemId];
                    queryItemIndex = this.query.findIndex(
                        (queryElem) =>
                            queryElem.searchItemId === firstActiveItem.searchItemId,
                    );
                    const { type } = firstSearchItem;
                    if (type === "favorite") {
                        const activeItemGroupBys =
                            this._getSearchItemGroupBys(firstActiveItem);
                        let createNewGroupBys = Boolean(activeItemGroupBys.length);
                        if (
                            createNewGroupBys &&
                            this.defaultGroupBy &&
                            this.env.config.viewType === "kanban"
                        ) {
                            const currentGroupBy = this._getGroupBy({
                                fallbackOnDefault: false,
                            });
                            if (
                                JSON.stringify(currentGroupBy) ===
                                JSON.stringify(this.defaultGroupBy)
                            ) {
                                createNewGroupBys = false;
                            }
                        }
                        if (createNewGroupBys) {
                            const newGroupByIds = [];
                            for (const activeItemGroupBy of activeItemGroupBys) {
                                const [fieldName, interval] =
                                    activeItemGroupBy.split(":");
                                const newGroupById = this.createNewGroupBy(fieldName, {
                                    interval,
                                    invisible: true,
                                });
                                if (newGroupById !== undefined) {
                                    newGroupByIds.push(newGroupById);
                                }
                            }
                            const isNewGroupBy = (queryElem) =>
                                newGroupByIds.includes(queryElem.searchItemId);
                            this.query = [
                                ...this.query.filter(isNewGroupBy),
                                ...this.query.filter(
                                    (queryElem) => !isNewGroupBy(queryElem),
                                ),
                            ];
                        }
                    }
                    this.deactivateGroup(groupId);
                }

                const newFilterIds = preFilters.flatMap((preFilter) =>
                    this.createNewFilters([preFilter]),
                );

                if (queryItemIndex !== undefined) {
                    const isNewFilter = (queryElem) =>
                        newFilterIds.includes(queryElem.searchItemId);
                    const newQueryElems = this.query.filter(isNewFilter);
                    const otherQueryElems = this.query.filter(
                        (queryElem) => !isNewFilter(queryElem),
                    );
                    this.query = [
                        ...otherQueryElems.slice(0, queryItemIndex),
                        ...newQueryElems,
                        ...otherQueryElems.slice(queryItemIndex),
                    ];
                }
            });

            await this._notify();
        }
    };
