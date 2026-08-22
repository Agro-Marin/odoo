// @ts-check
/** @odoo-module native */

import {
    deserializeDate,
    deserializeDateTime,
    formatDate,
    formatDateTime,
} from "@web/core/l10n/dates";
import { registry } from "@web/core/registry";
import { _t } from "@web/core/translation";
import {
    condition,
    Expression,
    isTree,
    normalizeValue,
} from "@web/core/tree/condition_tree";
import { constructTreeFromDomain } from "@web/core/tree/construct_tree_from_domain";
import { IN_RANGE_OPTIONS } from "@web/core/tree/in_range_options";
import { describeInRangeProviderOption } from "@web/core/tree/in_range_providers";
import { getOperatorLabel } from "@web/core/tree/operator_labels";
import { disambiguate, getResModel, isId } from "@web/core/tree/utils";
import { introduceVirtualOperators } from "@web/core/tree/virtual_operators";
import { unique, zip } from "@web/core/utils/collections/arrays";

/**
 * @param {import("@web/core/tree/condition_tree").Value} val
 * @param {boolean} disambiguate
 * @param {Record<string, any> | null} fieldDef
 * @param {Record<number, string>} displayNames
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
 * @param {any} tree
 * @param {boolean} [lookInSubTrees=false]
 * @returns {any[]}
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

/**
 * @param {any} tree
 * @param {boolean} [lookInSubTrees=false]
 * @returns {any[]}
 */
function getPathsInTree(tree, lookInSubTrees = false) {
    return unique(collectPaths(tree, lookInSubTrees));
}

/**
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
    /** @type {Map<string, { elems: any[], index: number }>} */
    const childrenByPath = new Map();
    for (const child of processedChildren) {
        if (
            child.type === "connector" ||
            child.negate ||
            typeof child.path !== "string" ||
            !["=", "in"].includes(child.operator) ||
            (child.operator === "in" && !Array.isArray(child.value))
        ) {
            children.push(child);
        } else {
            let entry = childrenByPath.get(child.path);
            if (!entry) {
                entry = { elems: [], index: children.length };
                childrenByPath.set(child.path, entry);
                children.push(child);
            }
            entry.elems.push(child);
        }
    }
    for (const [path, { elems, index }] of childrenByPath) {
        if (elems.length === 1) {
            continue;
        }
        const value = [];
        for (const child of elems) {
            if (child.operator === "=") {
                value.push(child.value);
            } else {
                value.push(...child.value);
            }
        }
        children[index] = condition(path, "in", normalizeValue(unique(value)));
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
 * @param {{ values: any[], join: string, addParenthesis: boolean, bracketWhenNested?: boolean }} valueDescription
 * @param {boolean} [isNested=false]
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
 * @param {any} tree
 * @param {(path: string) => Record<string, any> | null} getFieldDef
 * @param {Map<string, number[]>} idsByModel
 * @returns {Map<string, number[]>}
 */
function _extractIdsRecursive(tree, getFieldDef, idsByModel) {
    if (tree.type === "condition") {
        const fieldDef = getFieldDef(tree.path);
        if (["many2one", "many2many", "one2many"].includes(fieldDef?.type)) {
            const value = tree.value;
            const values = Array.isArray(value) ? value : [value];
            const ids = values.filter((val) => isId(val));
            const resModel = getResModel(fieldDef);
            if (ids.length && typeof resModel === "string" && resModel) {
                let modelIds = idsByModel.get(resModel);
                if (!modelIds) {
                    modelIds = [];
                    idsByModel.set(resModel, modelIds);
                }
                modelIds.push(...ids);
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
 * @param {import("@web/core/tree/condition_tree").Tree} tree
 * @param {(path: string) => Record<string, any> | null} getFieldDef
 * @returns {Map<string, number[]>}
 */
function extractIdsFromTree(tree, getFieldDef) {
    const idsByModel = _extractIdsRecursive(tree, getFieldDef, new Map());

    for (const [resModel, ids] of idsByModel) {
        idsByModel.set(resModel, unique(ids));
    }

    return idsByModel;
}

/**
 * @typedef {Object} TreeContext
 * @property {(path: string) => Record<string, any> | null} getFieldDef
 * @property {(node: any) => ConditionDescription} getConditionDescription
 */

/**
 * @typedef {Object} ConditionDescription
 * @property {string} pathDescription
 * @property {string} operatorDescription
 * @property {{ values: any[], join: string, addParenthesis: boolean, bracketWhenNested: boolean } | null} valueDescription
 */

class TreeProcessorService {
    /**
     * @param {{ field: any, name: any }} services
     */
    constructor({ field: fieldService, name: nameService }) {
        this.fieldService = fieldService;
        this.nameService = nameService;
    }

    /**
     * @param {import("@web/core/tree/condition_tree").Tree} tree
     * @param {(path: string) => Record<string, any> | null} getFieldDef
     * @returns {Promise<Map<string, Record<number, string>>>}
     */
    async getDisplayNames(tree, getFieldDef) {
        const resIdsByModel = extractIdsFromTree(tree, getFieldDef);
        const proms = [];
        const resModels = [];
        for (const [resModel, resIds] of resIdsByModel) {
            resModels.push(resModel);
            proms.push(this.nameService.loadDisplayNames(resModel, resIds));
        }
        return new Map(zip(resModels, await Promise.all(proms)));
    }

    /**
     * @param {string} resModel
     * @param {import("@web/core/tree/condition_tree").Tree} tree
     * @param {number} [limit]
     * @returns {Promise<(path: string) => string | undefined>}
     */
    async makeGetPathDescriptions(resModel, tree, limit) {
        const paths = getPathsInTree(tree);
        const promises = [];
        const pathDescriptions = new Map();
        for (const path of paths) {
            promises.push(
                this.fieldService
                    .loadPathDescription(resModel, path)
                    .then(
                        (
                            /** @type {{ displayNames: string[] }} */ { displayNames },
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
     * @param {string} resModel
     * @param {import("@web/core/tree/condition_tree").Tree} tree
     * @param {number} [limit]
     * @param {number} [pathLimit]
     * @returns {Promise<TreeContext>}
     */
    async makeTreeContext(resModel, tree, limit, pathLimit) {
        const [getFieldDef, getPathDescription] = await Promise.all([
            this.makeGetFieldDef(resModel, tree),
            this.makeGetPathDescriptions(resModel, tree, pathLimit),
        ]);
        const displayNames = await this.getDisplayNames(tree, getFieldDef);
        return {
            getFieldDef,
            getConditionDescription: (node) =>
                this._getConditionDescription(
                    node,
                    getFieldDef,
                    getPathDescription,
                    displayNames,
                    limit,
                ),
        };
    }

    /**
     * @param {string} resModel
     * @param {import("@web/core/tree/condition_tree").Tree} tree
     * @param {number} [limit]
     * @param {number} [pathLimit]
     * @returns {Promise<(node: any) => ConditionDescription>}
     */
    async makeGetConditionDescription(resModel, tree, limit, pathLimit) {
        const { getConditionDescription } = await this.makeTreeContext(
            resModel,
            simplifyTree(tree),
            limit,
            pathLimit,
        );
        return getConditionDescription;
    }

    /**
     * @param {Record<string, any>} node
     * @param {(path: string) => Record<string, any> | null} getFieldDef
     * @param {(path: string) => string | undefined} getPathDescription
     * @param {Map<string, Record<number, string>>} displayNames
     * @param {number} [limit=5]
     * @returns {ConditionDescription}
     */
    _getConditionDescription(
        node,
        getFieldDef,
        getPathDescription,
        displayNames,
        limit = 5,
    ) {
        const { negate, path } = node;
        let { operator, value } = node;
        const isRangeValue =
            operator === "in range" && Array.isArray(value) && value.length === 4;
        const periodLabel = isRangeValue
            ? describeInRangeProviderOption(value[0], value[2], value[3])
            : null;
        if (isRangeValue && value[1] === "custom range" && !periodLabel) {
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

        const coModeldisplayNames = displayNames.get(getResModel(fieldDef));
        const dis = disambiguate(value, coModeldisplayNames);
        let values;
        if (isRangeValue && operator === "in range") {
            const valueType = value[1];
            const opt = IN_RANGE_OPTIONS.find(([t]) => t === valueType);
            values = [periodLabel || (opt ? opt[1].toString() : String(valueType))];
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
        let bracketWhenNested = true;
        switch (operator) {
            case "between":
                join = _t("and");
                addParenthesis = false;
                bracketWhenNested = false;
                break;
            case "in range":
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
     * @param {string} resModel
     * @param {import("@web/core/tree/condition_tree").Tree} tree
     * @param {boolean} [isSubExpression=false]
     * @param {number} [limit]
     * @param {number} [pathLimit]
     * @returns {Promise<string>}
     */
    async getDomainTreeDescription(
        resModel,
        tree,
        isSubExpression = false,
        limit = undefined,
        pathLimit = undefined,
    ) {
        const simplified = simplifyTree(tree);
        return this.describeSimplifiedTree(
            resModel,
            simplified,
            isSubExpression,
            await this.makeTreeContext(resModel, simplified, limit, pathLimit),
            limit,
            pathLimit,
        );
    }

    /**
     * @param {string} resModel
     * @param {import("@web/core/tree/condition_tree").Tree} tree
     * @param {boolean} isSubExpression
     * @param {TreeContext} ctx
     * @param {number} [limit]
     * @param {number} [pathLimit]
     * @returns {Promise<string>}
     */
    async describeSimplifiedTree(
        resModel,
        tree,
        isSubExpression,
        ctx,
        limit,
        pathLimit,
    ) {
        if (tree.type === "connector") {
            const childDescriptions = tree.children.map((node) =>
                this.describeSimplifiedTree(
                    resModel,
                    node,
                    true,
                    ctx,
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
            ctx.getConditionDescription(tree);
        const stringDescription = [pathDescription, operatorDescription];
        if (valueDescription) {
            stringDescription.push(
                formatValueDescription(valueDescription, isSubExpression),
            );
        } else if (isTree(tree.value)) {
            const _fieldDef = ctx.getFieldDef(/** @type {any} */ (tree).path);
            const _resModel = getResModel(_fieldDef);
            const _tree = /** @type {any} */ (tree.value);
            const description = await this.getDomainTreeDescription(
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
     * @param {string} resModel
     * @param {import("@web/core/tree/condition_tree").Tree} tree
     * @param {number} [depth=0]
     * @returns {Promise<string[]>}
     */
    async getTooltipLines(resModel, tree, depth = 0) {
        const simplified = simplifyTree(tree);
        return this.tooltipLinesOfSimplifiedTree(
            resModel,
            simplified,
            depth,
            await this.makeTreeContext(resModel, simplified, 20),
        );
    }

    /**
     * @param {string} resModel
     * @param {import("@web/core/tree/condition_tree").Tree} tree
     * @param {number} depth
     * @param {TreeContext} ctx
     * @returns {Promise<string[]>}
     */
    async tooltipLinesOfSimplifiedTree(resModel, tree, depth, ctx) {
        const tabs = " ".repeat(depth * 4);
        if (tree.type === "connector") {
            let connector = tree.value === "&" ? _t("all") : _t("any");
            if (tree.negate) {
                connector = tree.value === "&" ? _t("not all") : _t("none");
            }
            connector = `${tabs}${connector}`;
            const childrenTooltipLines = await Promise.all(
                tree.children.map((node) =>
                    this.tooltipLinesOfSimplifiedTree(resModel, node, depth + 1, ctx),
                ),
            );
            return [connector, ...childrenTooltipLines].flat();
        }
        const { pathDescription, operatorDescription, valueDescription } =
            ctx.getConditionDescription(tree);
        const descr = [];
        const stringDescriptions = [pathDescription, operatorDescription];
        if (valueDescription) {
            stringDescriptions.push(formatValueDescription(valueDescription));
        }
        descr.push(`${tabs}${stringDescriptions.join(" ")}`);
        if (isTree(tree.value)) {
            const _fieldDef = ctx.getFieldDef(/** @type {any} */ (tree).path);
            const _resModel = getResModel(_fieldDef);
            const _tree = /** @type {any} */ (tree.value);
            const tooltipLines = await this.getTooltipLines(
                _resModel,
                _tree,
                depth + 1,
            );
            descr.push(...tooltipLines);
        }
        return descr;
    }

    /**
     * @param {string} resModel
     * @param {import("@web/core/tree/condition_tree").Tree} tree
     * @returns {Promise<string>}
     */
    async getDomainTreeTooltip(resModel, tree) {
        const descriptions = await this.getTooltipLines(resModel, tree);
        return descriptions.join("\n");
    }

    /**
     * @param {string} resModel
     * @param {import("@web/core/tree/condition_tree").Tree} tree
     * @returns {Promise<(path: string) => Record<string, any> | null>}
     */
    async makeGetFieldDef(resModel, tree) {
        const paths = new Set(getPathsInTree(tree, true));
        const promises = [];
        /** @type {Map<string, any>} */
        const fieldDefs = new Map();
        for (const path of paths) {
            promises.push(
                this.fieldService
                    .loadFieldInfo(resModel, path)
                    .then((/** @type {{ fieldDef: any }} */ { fieldDef }) => {
                        fieldDefs.set(path, fieldDef);
                    }),
            );
        }
        await Promise.all(promises);
        return (path) => {
            if (typeof path === "string") {
                return fieldDefs.get(path) ?? null;
            }
            return null;
        };
    }

    /**
     * @param {string} resModel
     * @param {any[]} domain
     * @param {boolean} [distributeNot=true]
     * @returns {Promise<import("@web/core/tree/condition_tree").Tree>}
     */
    async treeFromDomain(resModel, domain, distributeNot = true) {
        const tree = constructTreeFromDomain(domain, distributeNot);
        const getFieldDef = await this.makeGetFieldDef(resModel, tree);
        return introduceVirtualOperators(tree, {
            getFieldDef: /** @type {any} */ (getFieldDef),
        });
    }
}

const treeProcessorService = {
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
     * @returns {TreeProcessorService}
     */
    start(_env, services) {
        return new TreeProcessorService(services);
    },
};

registry.category("services").add("tree_processor", treeProcessorService);
