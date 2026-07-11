// @ts-check
/** @odoo-module native */

/** @module @web/search/search_split_domain - Domain-splitting logic that decomposes compound filters into individual search items */

/**
 * Receives the SearchModel instance as first argument (delegation pattern),
 * preserving subclass polymorphism for all internal method calls.
 */

import { makeContext } from "@web/core/context";
import { domainFromTree } from "@web/core/tree/domain_from_tree";
import { withNotificationsBlocked } from "@web/search/search_query_mutations";
/** The delegate seam contract — see the SearchModelLike typedef for the
 * instance state this module may read or write. */
/** @typedef {import("./search_model").SearchModelLike} SearchModel */

/**
 * Split a domain into individual filter conditions and add them to the search.
 *
 * Decomposes a top-level "&"-connected domain into its children, creates
 * invisible filter search items for each, and optionally replaces an
 * existing query group (preserving its position and group-by settings).
 *
 * @param {SearchModel} searchModel - the SearchModel instance
 * @param {string} domain - the domain expression to split
 * @param {number} [groupId] - optional query group to replace
 */
export async function splitAndAddDomain(searchModel, domain, groupId) {
    const group = groupId
        ? searchModel._getGroups().find((g) => g.id === groupId)
        : null;
    let context;
    if (group) {
        const contexts = [];
        for (const activeItem of group.activeItems) {
            const ctx = searchModel._getSearchItemContext(activeItem);
            if (ctx) {
                contexts.push(ctx);
            }
        }
        context = makeContext(contexts);
    }

    const tree = await searchModel.treeProcessor.treeFromDomain(
        searchModel.resModel,
        domain,
        !searchModel.isDebugMode,
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
            searchModel.treeProcessor.getDomainTreeDescription(
                searchModel.resModel,
                tree,
            ),
            searchModel.treeProcessor.getDomainTreeTooltip(searchModel.resModel, tree),
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

    // The block below is synchronous but can throw (createNewFilters /
    // createNewGroupBy / query splicing). withNotificationsBlocked guarantees
    // blockNotification is *restored* (not hardcoded to false) afterwards, so a
    // throw cannot wedge the search model into a permanently-silent state and
    // nesting inside another blocked window stays correct.
    withNotificationsBlocked(searchModel, () => {
        let queryItemIndex;
        if (group) {
            const firstActiveItem = group.activeItems[0];
            const firstSearchItem =
                searchModel.searchItems[firstActiveItem.searchItemId];
            queryItemIndex = searchModel.query.findIndex(
                (queryElem) => queryElem.searchItemId === firstActiveItem.searchItemId,
            );
            const { type } = firstSearchItem;
            if (type === "favorite") {
                const activeItemGroupBys =
                    searchModel._getSearchItemGroupBys(firstActiveItem);
                let createNewGroupBys = Boolean(activeItemGroupBys.length);
                if (
                    createNewGroupBys &&
                    searchModel.defaultGroupBy &&
                    searchModel.env.config.viewType === "kanban"
                ) {
                    const currentGroupBy = searchModel._getGroupBy({
                        fallbackOnDefault: false,
                    });
                    if (
                        JSON.stringify(currentGroupBy) ===
                        JSON.stringify(searchModel.defaultGroupBy)
                    ) {
                        createNewGroupBys = false;
                    }
                }
                if (createNewGroupBys) {
                    const newGroupByIds = [];
                    for (const activeItemGroupBy of activeItemGroupBys) {
                        const [fieldName, interval] = activeItemGroupBy.split(":");
                        newGroupByIds.push(
                            searchModel.createNewGroupBy(fieldName, {
                                interval,
                                invisible: true,
                            }),
                        );
                    }
                    // Move the new groupBys (pushed at the tail) to the front
                    // by identity — the previous index arithmetic assumed each
                    // createNewGroupBy pushed exactly one query element.
                    const isNewGroupBy = (queryElem) =>
                        newGroupByIds.includes(queryElem.searchItemId);
                    searchModel.query = [
                        ...searchModel.query.filter(isNewGroupBy),
                        ...searchModel.query.filter(
                            (queryElem) => !isNewGroupBy(queryElem),
                        ),
                    ];
                }
            }
            searchModel.deactivateGroup(groupId);
        }

        const newFilterIds = preFilters.flatMap((preFilter) =>
            searchModel.createNewFilters([preFilter]),
        );

        if (queryItemIndex !== undefined) {
            // Reinsert the new filters (identified by id, not by slice
            // arithmetic) at the position the replaced group occupied.
            const isNewFilter = (queryElem) =>
                newFilterIds.includes(queryElem.searchItemId);
            const newQueryElems = searchModel.query.filter(isNewFilter);
            const otherQueryElems = searchModel.query.filter(
                (queryElem) => !isNewFilter(queryElem),
            );
            searchModel.query = [
                ...otherQueryElems.slice(0, queryItemIndex),
                ...newQueryElems,
                ...otherQueryElems.slice(queryItemIndex),
            ];
        }
    });

    searchModel._notify();
}
