// @ts-check
/** @odoo-module native */

import { sortBy } from "@web/core/utils/collections/arrays";
/**
 * @param {Object} groupTree
 * @param {string[]} labels
 * @param {Array} values
 */
export function addGroup(groupTree, labels, values) {
    let tree = groupTree;
    for (const value of values.slice(0, -1)) {
        tree = tree.directSubTrees.get(value);
    }
    const value = values.at(-1);
    if (tree.directSubTrees.has(value)) {
        return;
    }
    tree.directSubTrees.set(value, {
        root: { labels, values },
        directSubTrees: new Map(),
    });
}

/**
 * @param {Record<string, any>} groupTree
 * @param {any[]} values
 * @returns {Record<string, any> | undefined}
 */
export function findGroup(groupTree, values) {
    let tree = groupTree;
    for (const value of values) {
        tree = tree.directSubTrees.get(value);
        if (!tree) {
            return undefined;
        }
    }
    return tree;
}

/**
 * @param {Object} tree
 * @param {Object} oldTree
 */
export function pruneTree(tree, oldTree) {
    if (!oldTree.directSubTrees.size) {
        tree.directSubTrees.clear();
        delete tree.sortedKeys;
        return;
    }
    for (const subTreeKey of [...tree.directSubTrees.keys()]) {
        const subTree = tree.directSubTrees.get(subTreeKey);
        if (!oldTree.directSubTrees.has(subTreeKey)) {
            subTree.directSubTrees.clear();
            delete subTree.sortedKeys;
        } else {
            pruneTree(subTree, oldTree.directSubTrees.get(subTreeKey));
        }
    }
}

/**
 * @param {Function} sortFunction
 * @param {Object} tree
 */
export function sortTree(sortFunction, tree) {
    tree.sortedKeys = sortBy([...tree.directSubTrees.keys()], sortFunction(tree));
    for (const subTree of tree.directSubTrees.values()) {
        sortTree(sortFunction, subTree);
    }
}

/**
 * @param {Object} tree
 */
export function stripSortedKeys(tree) {
    delete tree.sortedKeys;
    for (const subTree of tree.directSubTrees.values()) {
        stripSortedKeys(subTree);
    }
}

/**
 * @param {Object} tree
 * @returns {number}
 */
export function getTreeHeight(tree) {
    const subTreeHeights = [...tree.directSubTrees.values()].map(getTreeHeight);
    return Math.max(0, ...subTreeHeights) + 1;
}

/**
 * @param {Object} tree
 * @returns {Object}
 */
export function getLeafCounts(tree) {
    const leafCounts = {};
    let leafCount;
    if (!tree.directSubTrees.size) {
        leafCount = 1;
    } else {
        leafCount = [...tree.directSubTrees.values()].reduce((acc, subTree) => {
            const subLeafCounts = getLeafCounts(subTree);
            Object.assign(leafCounts, subLeafCounts);
            return acc + leafCounts[JSON.stringify(subTree.root.values)];
        }, 0);
    }
    leafCounts[JSON.stringify(tree.root.values)] = leafCount;
    return leafCounts;
}

/**
 * @param {Object} data
 * @returns {boolean}
 */
export function hasData(data) {
    const key = JSON.stringify([[], []]);
    return data.counts[key] > 0;
}
