// @ts-check
/** @odoo-module native */

/** @module @web/services/tree_processor_service - Converts domains to condition trees with human-readable descriptions and tooltips */

import {
    deserializeDate,
    deserializeDateTime,
    formatDate,
    formatDateTime,
} from "@web/core/l10n/dates";
import { _t } from "@web/core/l10n/translation";
import { registry } from "@web/core/registry";
import {
    condition,
    Expression,
    isTree,
    normalizeValue,
} from "@web/core/tree/condition_tree";
import { constructTreeFromDomain } from "@web/core/tree/construct_tree_from_domain";
import { IN_RANGE_OPTIONS } from "@web/core/tree/in_range_options";
import { getOperatorLabel } from "@web/core/tree/operator_labels";
import { disambiguate, getResModel, isId } from "@web/core/tree/utils";
import { introduceVirtualOperators } from "@web/core/tree/virtual_operators";
import { unique, zip } from "@web/core/utils/collections/arrays";

/**
 * Format a condition value for display in domain descriptions.
 * Resolves record IDs to display names, selection labels, and date formatting.
 * @param {import("@web/core/tree/condition_tree").Value} val
 * @param {boolean} disambiguate - whether to JSON-stringify string values
 * @param {Record<string, any> | null} fieldDef - field definition from the field service
 * @param {Record<number, string>} displayNames - map of record IDs to display names
 * @returns {string | import("@web/core/tree/condition_tree").Value}
 */
function formatValue(val, disambiguate, fieldDef, displayNames) {
    if (val instanceof Expression) {
        return val.toString();
    }
    if (displayNames && isId(val)) {
        if (typeof displayNames[/** @type {any} */ (val)] === "string") {
            val = displayNames[/** @type {any} */ (val)];
        } else {
            return _t("Inaccessible/missing record ID: %s", val);
        }
    }
    if (fieldDef?.type === "selection") {
        const [, label] =
            (fieldDef.selection || []).find(
                (/** @type {[any, string]} */ [v]) => v === val,
            ) || [];
        if (label !== undefined) {
            val = label;
        }
    }
    if (typeof val === "string") {
        if (fieldDef?.type === "datetime") {
            return formatDateTime(deserializeDateTime(val));
        }
        if (fieldDef?.type === "date") {
            return formatDate(deserializeDate(val));
        }
    }
    if (disambiguate && typeof val === "string") {
        return JSON.stringify(val);
    }
    return val;
}

/**
 * Collect all field paths referenced in a condition tree.
 * @param {any} tree
 * @param {boolean} [lookInSubTrees=false] - whether to recurse into sub-expression trees
 * @returns {any[]} unique field paths found in the tree
 */
function collectPaths(tree, lookInSubTrees = false) {
    const paths = [];
    if (tree.type === "condition") {
        paths.push(tree.path);
        if (typeof tree.path === "string" && lookInSubTrees && isTree(tree.value)) {
            for (const p of collectPaths(tree.value, lookInSubTrees)) {
                if (typeof p === "string") {
                    paths.push(`${tree.path}.${p}`);
                }
            }
        }
    }
    if (tree.type === "connector" && tree.children) {
        for (const child of tree.children) {
            paths.push(...collectPaths(child, lookInSubTrees));
        }
    }
    return paths;
}

function getPathsInTree(tree, lookInSubTrees = false) {
    return unique(collectPaths(tree, lookInSubTrees));
}

/**
 * Simplify a condition tree by merging multiple `=` / `in` conditions on the
 * same field path (under OR connectors) into a single `in` condition.
 *
 * Only NON-negated children may merge: `a = 1 or a = 2` is `a in [1, 2]`, but
 * `a != 1 or a != 2` is a tautology, whereas the merged `a not in [1, 2]` is
 * its near-opposite (De Morgan turns the OR into an AND). A negated child is
 * therefore passed through untouched.
 * @param {any} tree
 * @returns {any}
 */
export function simplifyTree(tree) {
    if (tree.type === "condition") {
        return tree;
    }
    const processedChildren = tree.children.map(simplifyTree);
    if (tree.value === "&") {
        return { ...tree, children: processedChildren };
    }
    const children = [];
    /** @type {Record<string, { elems: any[], index: number }>} */
    const childrenByPath = {};
    for (const child of processedChildren) {
        if (
            child.type === "connector" ||
            child.negate ||
            typeof child.path !== "string" ||
            !["=", "in"].includes(child.operator)
        ) {
            children.push(child);
        } else {
            if (!childrenByPath[child.path]) {
                childrenByPath[child.path] = { elems: [], index: children.length };
                children.push(child);
            }
            childrenByPath[child.path].elems.push(child);
        }
    }
    for (const path of Object.keys(childrenByPath)) {
        if (childrenByPath[path].elems.length === 1) {
            continue;
        }
        const value = [];
        for (const child of childrenByPath[path].elems) {
            if (child.operator === "=") {
                value.push(child.value);
            } else {
                value.push(...child.value);
            }
        }
        children[childrenByPath[path].index] = condition(
            path,
            "in",
            normalizeValue(unique(value)),
        );
    }
    if (children.length === 1) {
        const only = { ...children[0] };
        if (tree.negate) {
            only.negate = !only.negate;
        }
        return only;
    }
    return { ...tree, children };
}

/**
 * Render a condition's value part: the values joined by their connector word.
 *
 * A multi-value list is additionally bracketed when the condition is rendered
 * INSIDE a larger expression, because its own ``join`` is then indistinguishable
 * from the connector between sibling conditions — "a = 1 or 2 or b = 3" does not
 * say where the first condition ends, "a = ( 1 or 2 ) or b = 3" does. Standalone
 * renderings (one facet, one tooltip line, one tree-editor row) stay unbracketed:
 * there is no sibling to confuse them with, so brackets would be pure noise.
 *
 * @param {{ values: any[], join: string, addParenthesis: boolean, bracketWhenNested?: boolean }} valueDescription
 * @param {boolean} [isNested=false] the condition is a child of a connector in a
 *   single-string rendering
 * @returns {string}
 */
function formatValueDescription(
    { values, join, addParenthesis, bracketWhenNested },
    isNested = false,
) {
    const jointedValues = values.join(` ${join} `);
    const bracketed =
        addParenthesis || (isNested && bracketWhenNested && values.length > 1);
    return bracketed ? `( ${jointedValues} )` : jointedValues;
}

/**
 * Recursively extract record IDs from relational conditions in a tree.
 * @param {any} tree
 * @param {(path: string) => Record<string, any> | null} getFieldDef
 * @param {Record<string, number[]>} idsByModel - accumulator, mutated in place
 * @returns {Record<string, number[]>} the same idsByModel accumulator
 */
function _extractIdsRecursive(tree, getFieldDef, idsByModel) {
    if (tree.type === "condition") {
        const fieldDef = getFieldDef(tree.path);
        if (["many2one", "many2many", "one2many"].includes(fieldDef?.type)) {
            const value = tree.value;
            const values = Array.isArray(value) ? value : [value];
            const ids = values.filter((val) => isId(val));
            const resModel = getResModel(fieldDef);
            if (ids.length) {
                if (!idsByModel[resModel]) {
                    idsByModel[resModel] = [];
                }
                idsByModel[resModel].push(...ids);
            }
        }
    }
    if (tree.type === "connector") {
        for (const child of tree.children) {
            _extractIdsRecursive(child, getFieldDef, idsByModel);
        }
    }
    return idsByModel;
}

/**
 * Extract all record IDs from relational conditions, grouped by co-model.
 * @param {import("@web/core/tree/condition_tree").Tree} tree
 * @param {(path: string) => Record<string, any> | null} getFieldDef
 * @returns {Record<string, number[]>} map of model name to unique record IDs
 */
function extractIdsFromTree(tree, getFieldDef) {
    const idsByModel = _extractIdsRecursive(tree, getFieldDef, {});

    for (const resModel of Object.keys(idsByModel)) {
        idsByModel[resModel] = unique(idsByModel[resModel]);
    }

    return idsByModel;
}

/**
 * @typedef {Object} TreeProcessorServiceAPI
 * @property {(resModel: string, tree: import("@web/core/tree/condition_tree").Tree, isSubExpression?: boolean, limit?: number, pathLimit?: number) => Promise<string>} getDomainTreeDescription
 * @property {(resModel: string, tree: import("@web/core/tree/condition_tree").Tree) => Promise<string>} getDomainTreeTooltip
 * @property {(resModel: string, tree: import("@web/core/tree/condition_tree").Tree, limit?: number, pathLimit?: number) => Promise<(node: any) => ConditionDescription>} makeGetConditionDescription
 * @property {(resModel: string, tree: import("@web/core/tree/condition_tree").Tree) => Promise<(path: string) => Record<string, any> | null>} makeGetFieldDef
 * @property {(resModel: string, domain: any[], distributeNot?: boolean) => Promise<import("@web/core/tree/condition_tree").Tree>} treeFromDomain
 */

/**
 * @typedef {Object} ConditionDescription
 * @property {string} pathDescription - human-readable field path
 * @property {string} operatorDescription - operator label
 * @property {{ values: any[], join: string, addParenthesis: boolean, bracketWhenNested: boolean } | null} valueDescription
 */

/**
 * Service for processing domain condition trees: converting domains to trees,
 * generating human-readable descriptions and tooltips, and resolving field
 * definitions and display names.
 */
export const treeProcessorService = {
    dependencies: ["field", "name"],
    async: [
        "getDomainTreeDescription",
        "getDomainTreeTooltip",
        "makeGetConditionDescription",
        "makeGetFieldDef",
        "treeFromDomain",
    ],
    /**
     * @param {import("@web/env").OdooEnv} _env
     * @param {{ field: any, name: any }} services
     * @returns {TreeProcessorServiceAPI}
     */
    start(_env, { field: fieldService, name: nameService }) {
        /**
         * Load display names for all relational record IDs in a tree.
         * @param {import("@web/core/tree/condition_tree").Tree} tree
         * @param {(path: string) => Record<string, any> | null} getFieldDef
         * @returns {Promise<Record<string, Record<number, string>>>} map of model to (id → displayName)
         */
        async function getDisplayNames(tree, getFieldDef) {
            const resIdsByModel = extractIdsFromTree(tree, getFieldDef);
            const proms = [];
            const resModels = [];
            for (const [resModel, resIds] of Object.entries(resIdsByModel)) {
                resModels.push(resModel);
                proms.push(nameService.loadDisplayNames(resModel, resIds));
            }
            return Object.fromEntries(zip(resModels, await Promise.all(proms)));
        }

        /**
         * Build a lookup function that maps field paths to human-readable descriptions.
         * @param {string} resModel
         * @param {import("@web/core/tree/condition_tree").Tree} tree
         * @param {number} [limit] - max segments in path description before truncating
         * @returns {Promise<(path: string) => string | undefined>}
         */
        async function makeGetPathDescriptions(resModel, tree, limit) {
            const paths = getPathsInTree(tree);
            const promises = [];
            const pathDescriptions = new Map();
            for (const path of paths) {
                promises.push(
                    fieldService
                        .loadPathDescription(resModel, path)
                        .then(
                            (
                                /** @type {{ displayNames: string[] }} */ {
                                    displayNames,
                                },
                            ) => {
                                pathDescriptions.set(
                                    path,
                                    `${displayNames.slice(0, limit).join(" \u2794 ")}${
                                        displayNames.length > limit ? "..." : ""
                                    }`,
                                );
                            },
                        ),
                );
            }
            await Promise.all(promises);
            return (path) => pathDescriptions.get(path);
        }

        /**
         * Body of {@link makeGetConditionDescription} for a tree the caller has
         * ALREADY simplified. The public entry point simplifies and delegates;
         * the two internal callers that simplify for their own recursion reuse
         * this directly instead of paying a second full-tree pass.
         * @param {string} resModel
         * @param {import("@web/core/tree/condition_tree").Tree} tree
         * @param {number} [limit]
         * @param {number} [pathLimit]
         * @returns {Promise<(node: any) => ConditionDescription>}
         */
        async function _makeGetConditionDescription(resModel, tree, limit, pathLimit) {
            const [getFieldDef, getPathDescription] = await Promise.all([
                makeGetFieldDef(resModel, tree),
                makeGetPathDescriptions(resModel, tree, pathLimit),
            ]);
            const displayNames = await getDisplayNames(tree, getFieldDef);
            return (node) =>
                _getConditionDescription(
                    node,
                    getFieldDef,
                    getPathDescription,
                    displayNames,
                    limit,
                );
        }

        /**
         * Create a function that returns a structured description for a condition node.
         * @param {string} resModel
         * @param {import("@web/core/tree/condition_tree").Tree} tree
         * @param {number} [limit] - max values to show before truncating
         * @param {number} [pathLimit] - max segments in path descriptions
         * @returns {Promise<(node: any) => ConditionDescription>}
         */
        function makeGetConditionDescription(resModel, tree, limit, pathLimit) {
            return _makeGetConditionDescription(
                resModel,
                simplifyTree(tree),
                limit,
                pathLimit,
            );
        }

        /**
         * Build a structured description of a single condition node.
         * @param {Record<string, any>} node - condition tree node
         * @param {(path: string) => Record<string, any> | null} getFieldDef
         * @param {(path: string) => string | undefined} getPathDescription
         * @param {Record<string, Record<number, string>>} displayNames
         * @param {number} [limit=5] - max values before truncating
         * @returns {ConditionDescription}
         */
        function _getConditionDescription(
            node,
            getFieldDef,
            getPathDescription,
            displayNames,
            limit = 5,
        ) {
            const { negate, path } = node;
            let { operator, value } = node;
            if (operator === "in range" && value[1] === "custom range") {
                operator = "between";
                value = value.slice(2);
            }
            if (["=", "!="].includes(operator) && value === false) {
                operator = operator === "=" ? "not set" : "set";
            }
            const fieldDef = getFieldDef(path);
            const operatorLabel = getOperatorLabel(
                operator,
                fieldDef?.type,
                negate,
                (operator) => {
                    switch (operator) {
                        case "=":
                        case "in":
                            return "=";
                        case "!=":
                        case "not in":
                            return _t("not =");
                        case "any":
                            return ":";
                        case "not any":
                            return _t(": not");
                    }
                },
            );

            const pathDescription = getPathDescription(path);
            /** @type {ConditionDescription} */
            const description = {
                pathDescription,
                operatorDescription: operatorLabel,
                valueDescription: null,
            };

            if (isTree(node.value)) {
                return description;
            }
            if (["set", "not set"].includes(operator)) {
                return description;
            }

            const coModeldisplayNames = displayNames[getResModel(fieldDef)];
            const dis = disambiguate(value, coModeldisplayNames);
            let values;
            if (operator === "in range") {
                const valueType = value[1];
                const opt = IN_RANGE_OPTIONS.find(([t]) => t === valueType);
                values = [(opt ? opt[1] : valueType).toString()];
            } else {
                const rawValues = Array.isArray(value) ? value : [value];
                const truncated = rawValues.length > limit;
                values = rawValues
                    .slice(0, truncated ? limit - 1 : limit)
                    .map((val) => formatValue(val, dis, fieldDef, coModeldisplayNames));
                if (truncated) {
                    values.push("...");
                }
            }

            let join;
            let addParenthesis = Array.isArray(value);
            // "between A and B" / "is in Today" read as fixed idioms, so their
            // join word is never mistaken for a connector between conditions.
            let bracketWhenNested = true;
            switch (operator) {
                case "between":
                    join = _t("and");
                    addParenthesis = false;
                    bracketWhenNested = false;
                    break;
                case "in range":
                    // Not `_t(" ")`: a lone space is not a translatable term,
                    // and it lands in the PO catalog as an entry no translator
                    // can act on (gettext also reserves the empty msgid for
                    // catalog metadata).
                    join = " ";
                    addParenthesis = false;
                    bracketWhenNested = false;
                    break;
                case "in":
                case "not in":
                    addParenthesis = !values.length;
                // falls through
                default:
                    join = _t("or");
            }
            description.valueDescription = {
                values,
                join,
                addParenthesis,
                bracketWhenNested,
            };
            return description;
        }

        /**
         * Generate a human-readable string description of a domain tree.
         * Connector nodes produce "X and Y" or "X or Y"; condition nodes
         * produce "Field operator value".
         * @param {string} resModel
         * @param {import("@web/core/tree/condition_tree").Tree} tree
         * @param {boolean} [isSubExpression=false] - whether to wrap in parentheses
         * @param {number} [limit] - max values per condition
         * @param {number} [pathLimit] - max path segments
         * @returns {Promise<string>}
         */
        async function getDomainTreeDescription(
            resModel,
            tree,
            isSubExpression = false,
            limit = undefined,
            pathLimit = undefined,
        ) {
            const simplified = simplifyTree(tree);
            return describeSimplifiedTree(
                resModel,
                simplified,
                isSubExpression,
                await _makeGetConditionDescription(
                    resModel,
                    simplified,
                    limit,
                    pathLimit,
                ),
                limit,
                pathLimit,
            );
        }

        /**
         * Recursive body of {@link getDomainTreeDescription}, taking an ALREADY
         * simplified tree and the tree-wide ``getConditionDescription`` closure.
         * ``simplifyTree`` recurses into children itself, so re-simplifying each
         * subtree on the way down was O(nodes x depth) of idempotent work.
         *
         * ``getConditionDescription`` is likewise resolved ONCE for the whole
         * tree and threaded down. Building it per leaf re-ran the full
         * resolution — field defs, path descriptions and display names — once
         * per condition, defeating the very batching those helpers exist to
         * provide (measured: 12 ``loadFieldInfo`` + 12 ``loadDisplayNames`` for
         * a 12-leaf tree that needs one of each). It also left the display-name
         * batching microtask-alignment-dependent: leaves at different depths
         * reach ``loadDisplayNames`` on different ticks and fragment into
         * separate RPCs.
         * @param {string} resModel
         * @param {import("@web/core/tree/condition_tree").Tree} tree
         * @param {boolean} isSubExpression
         * @param {(node: any) => ConditionDescription} getConditionDescription
         * @param {number} [limit]
         * @param {number} [pathLimit]
         * @returns {Promise<string>}
         */
        async function describeSimplifiedTree(
            resModel,
            tree,
            isSubExpression,
            getConditionDescription,
            limit,
            pathLimit,
        ) {
            if (tree.type === "connector") {
                const childDescriptions = tree.children.map((node) =>
                    describeSimplifiedTree(
                        resModel,
                        node,
                        true,
                        getConditionDescription,
                        limit,
                        pathLimit,
                    ),
                );
                const separator = tree.value === "&" ? _t("and") : _t("or");
                const descriptions = await Promise.all(childDescriptions);
                /** @type {string} */
                let description = descriptions.join(` ${separator} `);
                if (isSubExpression || tree.negate) {
                    description = `( ${description} )`;
                }
                if (tree.negate) {
                    description = `! ${description}`;
                }
                return description;
            }
            const { pathDescription, operatorDescription, valueDescription } =
                getConditionDescription(tree);
            const stringDescription = [pathDescription, operatorDescription];
            if (valueDescription) {
                stringDescription.push(
                    formatValueDescription(valueDescription, isSubExpression),
                );
            } else if (isTree(tree.value)) {
                const getFieldDef = await makeGetFieldDef(resModel, tree);
                const _fieldDef = getFieldDef(/** @type {any} */ (tree).path);
                const _resModel = getResModel(_fieldDef);
                const _tree = /** @type {any} */ (tree.value);
                // `limit`/`pathLimit` must cross into the sub-domain. They are
                // threaded through this whole recursion for this one call, and
                // dropping them here made them dead parameters: a caller asking
                // for a compact rendering (mass_mailing's snippet-visibility
                // facet passes 2/1) got the DEFAULTS back the moment the domain
                // contained an `any` sub-expression.
                const description = await getDomainTreeDescription(
                    _resModel,
                    _tree,
                    false,
                    limit,
                    pathLimit,
                );
                stringDescription.push(`( ${description} )`);
            }
            return stringDescription.join(" ");
        }

        /**
         * Build indented tooltip lines for a domain tree (used in popover tooltips).
         * @param {string} resModel
         * @param {import("@web/core/tree/condition_tree").Tree} tree
         * @param {number} [depth=0] - current indentation level
         * @returns {Promise<string[]>}
         */
        async function getTooltipLines(resModel, tree, depth = 0) {
            const simplified = simplifyTree(tree);
            return tooltipLinesOfSimplifiedTree(
                resModel,
                simplified,
                depth,
                await _makeGetConditionDescription(resModel, simplified, 20),
            );
        }

        /**
         * Recursive body of {@link getTooltipLines}, taking an ALREADY simplified
         * tree — see {@link describeSimplifiedTree}.
         * @param {string} resModel
         * @param {import("@web/core/tree/condition_tree").Tree} tree
         * @param {number} depth
         * @param {(node: any) => ConditionDescription} getConditionDescription
         *   resolved once for the whole tree — see {@link describeSimplifiedTree}
         * @returns {Promise<string[]>}
         */
        async function tooltipLinesOfSimplifiedTree(
            resModel,
            tree,
            depth,
            getConditionDescription,
        ) {
            const tabs = " ".repeat(depth * 4);
            if (tree.type === "connector") {
                let connector = tree.value === "&" ? _t("all") : _t("any");
                if (tree.negate) {
                    connector = tree.value === "&" ? _t("not all") : _t("none");
                }
                connector = `${tabs}${connector}`;
                const childrenTooltipLines = await Promise.all(
                    tree.children.map((node) =>
                        tooltipLinesOfSimplifiedTree(
                            resModel,
                            node,
                            depth + 1,
                            getConditionDescription,
                        ),
                    ),
                );
                return [connector, ...childrenTooltipLines].flat();
            }
            const { pathDescription, operatorDescription, valueDescription } =
                getConditionDescription(tree);
            const descr = [];
            const stringDescriptions = [pathDescription, operatorDescription];
            if (valueDescription) {
                stringDescriptions.push(formatValueDescription(valueDescription));
            }
            descr.push(`${tabs}${stringDescriptions.join(" ")}`);
            if (isTree(tree.value)) {
                const getFieldDef = await makeGetFieldDef(resModel, tree);
                const _fieldDef = getFieldDef(/** @type {any} */ (tree).path);
                const _resModel = getResModel(_fieldDef);
                const _tree = /** @type {any} */ (tree.value);
                const tooltipLines = await getTooltipLines(_resModel, _tree, depth + 1);
                descr.push(...tooltipLines);
            }
            return descr;
        }

        /**
         * Generate a multi-line tooltip string for a domain tree.
         * @param {string} resModel
         * @param {import("@web/core/tree/condition_tree").Tree} tree
         * @returns {Promise<string>}
         */
        async function getDomainTreeTooltip(resModel, tree) {
            const descriptions = await getTooltipLines(resModel, tree);
            return descriptions.join("\n");
        }

        /**
         * Build a lookup function that maps field paths to their field definitions.
         * Loads all field info for paths used in the tree in parallel.
         * @param {string} resModel
         * @param {import("@web/core/tree/condition_tree").Tree} tree
         * @returns {Promise<(path: string) => Record<string, any> | null>}
         */
        async function makeGetFieldDef(resModel, tree) {
            const paths = new Set(getPathsInTree(tree, true));
            const promises = [];
            /** @type {Record<string, any>} */
            const fieldDefs = {};
            for (const path of paths) {
                promises.push(
                    fieldService
                        .loadFieldInfo(resModel, path)
                        .then((/** @type {{ fieldDef: any }} */ { fieldDef }) => {
                            fieldDefs[path] = fieldDef;
                        }),
                );
            }
            await Promise.all(promises);
            return (path) => {
                if (typeof path === "string") {
                    return fieldDefs[path];
                }
                return null;
            };
        }

        /**
         * Convert a domain array into a condition tree with virtual operators.
         * @param {string} resModel
         * @param {any[]} domain - Odoo domain expression
         * @param {boolean} [distributeNot=true] - whether to push NOT down into leaves
         * @returns {Promise<import("@web/core/tree/condition_tree").Tree>}
         */
        async function treeFromDomain(resModel, domain, distributeNot = true) {
            const tree = constructTreeFromDomain(domain, distributeNot);
            const getFieldDef = await makeGetFieldDef(resModel, tree);
            return introduceVirtualOperators(tree, {
                getFieldDef: /** @type {any} */ (getFieldDef),
            });
        }

        return {
            getDomainTreeDescription,
            getDomainTreeTooltip,
            makeGetConditionDescription,
            makeGetFieldDef,
            treeFromDomain,
        };
    },
};

registry.category("services").add("tree_processor", treeProcessorService);
