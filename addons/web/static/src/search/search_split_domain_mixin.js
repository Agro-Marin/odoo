// @ts-check
/** @odoo-module native */

/** @module @web/search/search_split_domain_mixin - Domain-splitting logic mixed into SearchModel */

import { makeContext } from "@web/core/context";
import { domainFromTree } from "@web/core/tree/domain_from_tree";

/**
 * Domain-splitting logic for SearchModel: decomposes a compound "&"-connected
 * domain into individual (invisible) filter search items, optionally replacing
 * an existing query group in place.
 *
 * Mixed into SearchModel (``extends SearchSplitDomainMixin(...)``) rather than
 * kept as a pass-``this`` module function with a proxy method: the logic lives on
 * the prototype directly, using ``this``. Not overridden by any subclass (only
 * called, e.g. enterprise ``ai``). ``treeProcessor``/``query``/``searchItems`` and
 * the query-mutation methods live on SearchModel and are reached via ``this``.
 *
 * @template {new (...args: any[]) => any} T
 * @param {T} Base
 */
export const SearchSplitDomainMixin = (Base) =>
    class extends Base {
        /**
         * Split a domain into individual filter conditions and add them to the search.
         *
         * Decomposes a top-level "&"-connected domain into its children, creates
         * invisible filter search items for each, and optionally replaces an
         * existing query group (preserving its position and group-by settings).
         *
         * @param {string} domain - the domain expression to split
         * @param {number} [groupId] - optional query group to replace
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
                                newGroupByIds.push(
                                    this.createNewGroupBy(fieldName, {
                                        interval,
                                        invisible: true,
                                    }),
                                );
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

            this._notify();
        }
    };
