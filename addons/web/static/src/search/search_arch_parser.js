// @ts-check
/** @odoo-module native */

/** @module @web/search/search_arch_parser - Parses search view XML arch into structured filter, groupby, and search panel items */

import { makeContext } from "@web/core/context";
import { _t } from "@web/core/l10n/translation";
import { evaluateBooleanExpr, evaluateExpr } from "@web/core/py_js/py";
import { visitXML } from "@web/core/utils/dom/xml";
import { clamp } from "@web/core/utils/format/numbers";
import { DEFAULT_INTERVAL, toGeneratorId } from "@web/search/utils/dates";

const ALL = _t("All");
const DEFAULT_LIMIT = 200;
const DEFAULT_VIEWS_WITH_SEARCH_PANEL = ["kanban", "list"];

/**
 * Normalize an icon class value to FA7 format.
 * Bare FA4 names like 'fa-folder' are promoted to 'fa-solid fa-folder'.
 * Full FA7 class strings ('fa-solid …', 'fa-regular …', 'fa-brands …') pass through unchanged.
 * @param {string | null | undefined} iconClass
 * @returns {string | null}
 */
function _normalizeIconClass(iconClass) {
    if (!iconClass) {
        return null;
    }
    if (
        iconClass.startsWith("fa-solid") ||
        iconClass.startsWith("fa-regular") ||
        iconClass.startsWith("fa-brands")
    ) {
        return iconClass; // Already FA7 — no-op
    }
    // "fa-folder" → "fa-solid fa-folder"; legacy "fa fa-folder" →
    // "fa-solid fa-folder" (strip base class)
    const name = iconClass.startsWith("fa fa-") ? iconClass.slice(3) : iconClass;
    return `fa-solid ${name}`;
}

/**
 * Split the 'group_by' key from a context attribute; falls back to an
 * empty list for an invalid context or a missing 'group_by' key.
 * @param {string} context
 * @returns {string[]}
 */
function getContextGroupBy(context) {
    try {
        return makeContext([context]).group_by?.split(":") || [];
    } catch {
        return [];
    }
}

/**
 * Normalize extended search item types to their base type.
 * @param {string} type
 * @returns {string}
 */
function reduceType(type) {
    if (type === "dateFilter") {
        return "filter";
    }
    if (type === "dateGroupBy") {
        return "groupBy";
    }
    return type;
}

/**
 * Parser that transforms a `<search>` view architecture XML into structured
 * pre-search items, search panel sections, and label resolution callbacks.
 */
export class SearchArchParser {
    /**
     * @param {{ irFilters?: Object[], arch?: string }} searchViewDescription
     * @param {Record<string, Object>} fields - field definitions from the model
     * @param {Record<string, any>} [searchDefaults={}] - default search values from context
     * @param {Record<string, any>} [searchPanelDefaults={}] - default search panel selections
     */
    constructor(
        searchViewDescription,
        fields,
        searchDefaults = {},
        searchPanelDefaults = {},
    ) {
        const { irFilters, arch } = searchViewDescription;

        this.fields = fields || {};
        this.irFilters = irFilters || [];
        this.arch = arch || "<search/>";

        this.labels = [];
        this.preSearchItems = [];
        this.searchPanelInfo = {
            className: "",
            viewTypes: DEFAULT_VIEWS_WITH_SEARCH_PANEL,
        };
        this.sections = [];

        this.searchDefaults = searchDefaults;
        this.searchPanelDefaults = searchPanelDefaults;

        this.currentGroup = [];
        this.currentTag = null;
        this.groupNumber = 0;
        this.pregroupOfGroupBys = [];

        this.optionsParams = null;
    }

    /**
     * Walk the search arch XML and produce structured output.
     * @returns {{ labels: Function[], preSearchItems: Array[], searchPanelInfo: Object, sections: Array[] }}
     */
    parse() {
        visitXML(this.arch, (node, visitChildren) => {
            switch (node.tagName) {
                case "search":
                    this.visitSearch(node, visitChildren);
                    break;
                case "searchpanel":
                    return this.visitSearchPanel(node);
                case "group":
                    this.visitGroup(node, visitChildren);
                    break;
                case "separator":
                    this.visitSeparator();
                    break;
                case "field":
                    this.visitField(node);
                    break;
                case "filter":
                    if (this.optionsParams) {
                        this.visitDateOption(node);
                    } else {
                        this.visitFilter(node, visitChildren);
                    }
                    break;
            }
        });

        return {
            labels: this.labels,
            preSearchItems: this.preSearchItems,
            searchPanelInfo: this.searchPanelInfo,
            sections: this.sections,
        };
    }

    /**
     * Flush the current group of pre-search items and start a new one.
     * @param {string | null} [tag=null] - the type tag for the new group
     */
    pushGroup(tag = null) {
        if (this.currentGroup.length) {
            if (this.currentTag === "groupBy") {
                this.pregroupOfGroupBys.push(...this.currentGroup);
            } else {
                this.preSearchItems.push(this.currentGroup);
            }
        }
        this.currentTag = tag;
        this.currentGroup = [];
        this.groupNumber++;
    }

    /**
     * Process a `<field>` node: extract domain, operator, defaults, and label callbacks.
     * @param {Element} node
     */
    visitField(node) {
        this.pushGroup("field");
        const preField = { type: "field" };
        if (node.hasAttribute("invisible")) {
            preField.invisible = node.getAttribute("invisible");
        }
        if (node.hasAttribute("domain")) {
            preField.domain = node.getAttribute("domain");
        }
        if (node.hasAttribute("filter_domain")) {
            preField.filterDomain = node.getAttribute("filter_domain");
        } else if (node.hasAttribute("operator")) {
            preField.operator = node.getAttribute("operator");
        }
        if (node.hasAttribute("context")) {
            preField.context = node.getAttribute("context");
        }
        if (node.hasAttribute("name")) {
            const name = node.getAttribute("name");
            if (!this.fields[name]) {
                // Field not available (group-restricted or removed by a
                // module override): skip gracefully instead of crashing.
                return;
            }
            const fieldType = this.fields[name].type;
            preField.fieldName = name;
            preField.fieldType = fieldType;
            if (fieldType !== "properties" && name in this.searchDefaults) {
                preField.isDefault = true;
                const val = this.searchDefaults[name];
                const value = Array.isArray(val) ? val[0] : val;
                let operator = preField.operator;
                if (!operator) {
                    let type = fieldType;
                    if (node.hasAttribute("widget")) {
                        type = node.getAttribute("widget");
                    }
                    // many2one as a default filter has a numeric value
                    // instead of a string, so we want "=" not "ilike".
                    if (
                        ["char", "html", "many2many", "one2many", "text"].includes(type)
                    ) {
                        operator = "ilike";
                    } else {
                        operator = "=";
                    }
                }
                preField.defaultRank = -10;
                const { selection, context, relation } = this.fields[name];
                preField.defaultAutocompleteValue = {
                    label: `${value}`,
                    operator,
                    value,
                };
                if (fieldType === "selection") {
                    const option = selection.find((sel) => sel[0] === value);
                    if (option) {
                        preField.defaultAutocompleteValue.label = option[1];
                    }
                    // No matching option (e.g. stale value in the action
                    // context): keep the raw value as label instead of
                    // crashing the entire search view.
                } else if (fieldType === "many2one") {
                    this.labels.push(async (orm) => {
                        // The record may no longer exist or be inaccessible
                        // (stale id in the action context): `read` REJECTS with
                        // MissingError/AccessError (not []), so the fallback
                        // must catch — otherwise SearchModel.load() rejects and
                        // crashes the entire search view.
                        let results;
                        try {
                            results = await orm.silent.call(
                                relation,
                                "read",
                                [value, ["display_name"]],
                                { context },
                            );
                        } catch {
                            results = [];
                        }
                        preField.defaultAutocompleteValue.label =
                            results[0]?.display_name ?? String(value);
                    });
                } else if (
                    ["many2many", "one2many"].includes(fieldType) &&
                    Array.isArray(val) &&
                    val.every((v) => Number.isInteger(v) && v > 0)
                ) {
                    preField.defaultAutocompleteValue.operator = "in";
                    preField.defaultAutocompleteValue.value = val;
                    this.labels.push(async (orm) => {
                        // Same stale-id hardening as the many2one branch.
                        let results;
                        try {
                            results = await orm.silent.call(
                                relation,
                                "read",
                                [val, ["display_name"]],
                                { context },
                            );
                        } catch {
                            results = [];
                        }
                        preField.defaultAutocompleteValue.label =
                            results.map((r) => r["display_name"]).join(" or ") ||
                            String(val);
                    });
                }
            }
        } else {
            // Normally caught earlier by server-side view arch validation.
            throw new Error(
                "Invalid search view arch: a <field> node has no 'name' attribute.",
            );
        }
        if (node.hasAttribute("string")) {
            preField.description = node.getAttribute("string");
        } else if (preField.fieldName && this.fields[preField.fieldName]) {
            preField.description = this.fields[preField.fieldName].string;
        } else {
            preField.description = "Ω";
        }
        this.currentGroup.push(preField);
    }

    /**
     * Process a `<filter>` node: detect type (filter, groupBy, dateGroupBy, dateFilter),
     * handle defaults, and push to the current group.
     * @param {Element} node
     * @param {() => void} visitChildren
     */
    visitFilter(node, visitChildren) {
        const preSearchItem = { type: "filter" };
        if (node.hasAttribute("context")) {
            const context = node.getAttribute("context");
            const [fieldName, defaultInterval] = getContextGroupBy(context);
            const groupByField = this.fields[fieldName];
            if (groupByField) {
                preSearchItem.type = "groupBy";
                preSearchItem.fieldName = fieldName;
                preSearchItem.fieldType = groupByField.type;
                if (["date", "datetime"].includes(groupByField.type)) {
                    preSearchItem.type = "dateGroupBy";
                    preSearchItem.defaultIntervalId =
                        defaultInterval || DEFAULT_INTERVAL;
                }
            } else {
                preSearchItem.context = context;
            }
        }
        if (reduceType(preSearchItem.type) !== this.currentTag) {
            this.pushGroup(reduceType(preSearchItem.type));
        }
        if (preSearchItem.type === "filter") {
            if (node.hasAttribute("date")) {
                const fieldName = node.getAttribute("date");
                const dateField = this.fields[fieldName];
                if (!dateField) {
                    // Field not available (e.g. group-restricted) — skip this filter.
                    return;
                }
                preSearchItem.type = "dateFilter";
                preSearchItem.fieldName = fieldName;
                preSearchItem.fieldType = dateField.type;
                const optionsParams = {
                    startYear: Number(node.getAttribute("start_year") || -2),
                    endYear: Number(node.getAttribute("end_year") || 0),
                    startMonth: Number(node.getAttribute("start_month") || -2),
                    endMonth: Number(node.getAttribute("end_month") || 0),
                    customOptions: [],
                };
                if (optionsParams.endMonth < optionsParams.startMonth) {
                    // Unvalidated arch input: an inverted month window makes
                    // getMonthPeriodOptions throw (invalid array length),
                    // crashing the whole search view — normalize it instead.
                    console.warn(
                        `[search] <filter date="${fieldName}">: end_month (${optionsParams.endMonth}) ` +
                            `is lower than start_month (${optionsParams.startMonth}); swapping them.`,
                    );
                    [optionsParams.startMonth, optionsParams.endMonth] = [
                        optionsParams.endMonth,
                        optionsParams.startMonth,
                    ];
                }
                // Current month (offset 0) clamped into the window — clamp's
                // signature is (num, min, max); the previous arg order always
                // yielded endMonth for any non-default window.
                const defaultOffset = clamp(
                    0,
                    optionsParams.startMonth,
                    optionsParams.endMonth,
                );
                preSearchItem.defaultGeneratorIds = [
                    toGeneratorId("month", defaultOffset),
                ];
                if (node.hasAttribute("default_period")) {
                    preSearchItem.defaultGeneratorIds = node
                        .getAttribute("default_period")
                        .split(",");
                }
                this.optionsParams = optionsParams;
                visitChildren();
                preSearchItem.optionsParams = optionsParams;
                this.optionsParams = null;
            }
            preSearchItem.domain = node.getAttribute("domain") || "[]";
        }
        if (node.hasAttribute("invisible")) {
            preSearchItem.invisible = node.getAttribute("invisible");
            const fieldName = preSearchItem.fieldName;
            if (fieldName && !this.fields[fieldName]) {
                // A field limited to specific groups may still appear in the
                // view (in 'invisible' state); discard the related filter.
                return;
            }
        }
        preSearchItem.groupNumber = this.groupNumber;
        if (node.hasAttribute("name")) {
            const name = node.getAttribute("name");
            preSearchItem.name = name;
            if (name in this.searchDefaults) {
                preSearchItem.isDefault = true;
                const value = this.searchDefaults[name];
                if (["groupBy", "dateGroupBy"].includes(preSearchItem.type)) {
                    preSearchItem.defaultRank = typeof value === "number" ? value : 100;
                } else {
                    preSearchItem.defaultRank = -5;
                }
                if (
                    preSearchItem.type === "dateFilter" &&
                    typeof value === "string" &&
                    !/^(true|1)$/i.test(value)
                ) {
                    preSearchItem.defaultGeneratorIds = value.split(",");
                }
            }
        }
        if (node.hasAttribute("string")) {
            preSearchItem.description = node.getAttribute("string");
        } else if (preSearchItem.fieldName && this.fields[preSearchItem.fieldName]) {
            preSearchItem.description = this.fields[preSearchItem.fieldName].string;
        } else if (node.hasAttribute("help")) {
            preSearchItem.description = node.getAttribute("help");
        } else if (node.hasAttribute("name")) {
            preSearchItem.description = node.getAttribute("name");
        } else {
            preSearchItem.description = "Ω";
        }
        this.currentGroup.push(preSearchItem);
    }

    /**
     * Process a `<filter>` child of a date filter — adds a custom period option.
     * @param {Element} node
     */
    visitDateOption(node) {
        const preDateOption = { type: "dateOption" };
        for (const attribute of ["name", "string", "domain"]) {
            if (!node.getAttribute(attribute)) {
                throw new Error(`Attribute "${attribute}" is missing.`);
            }
        }
        preDateOption.id = `custom_${node.getAttribute("name")}`;
        preDateOption.description = node.getAttribute("string");
        preDateOption.domain = node.getAttribute("domain");
        this.optionsParams.customOptions.push(preDateOption);
    }

    /**
     * Process a `<group>` node: flush current group, visit children, flush again.
     * @param {Element} node
     * @param {() => void} visitChildren
     */
    visitGroup(node, visitChildren) {
        this.pushGroup();
        visitChildren();
        this.pushGroup();
    }

    /**
     * Process the root `<search>` node.
     * @param {Element} node
     * @param {() => void} visitChildren
     */
    visitSearch(node, visitChildren) {
        visitChildren();
        this.pushGroup();
        if (this.pregroupOfGroupBys.length) {
            this.preSearchItems.push(this.pregroupOfGroupBys);
        }
    }

    /**
     * Process the `<searchpanel>` node: build category and filter sections.
     * @param {Element} searchPanelNode
     * @returns {false} stops the visitor from descending into children
     */
    visitSearchPanel(searchPanelNode) {
        let hasCategoryWithCounters = false;
        let hasFilterWithDomain = false;
        let nextSectionId = 1;

        if (searchPanelNode.hasAttribute("class")) {
            this.searchPanelInfo.className = searchPanelNode.getAttribute("class");
        }
        if (searchPanelNode.hasAttribute("view_types")) {
            this.searchPanelInfo.viewTypes = searchPanelNode
                .getAttribute("view_types")
                .split(",");
        }

        for (const node of searchPanelNode.children) {
            if (node.nodeType !== 1 || node.tagName !== "field") {
                continue;
            }
            if (
                node.getAttribute("invisible") === "True" ||
                node.getAttribute("invisible") === "1"
            ) {
                continue;
            }
            const attrs = {};
            for (const attrName of node.getAttributeNames()) {
                attrs[attrName] = node.getAttribute(attrName);
            }

            const type = attrs.select === "multi" ? "filter" : "category";
            const section = {
                color: attrs.color || null,
                description:
                    attrs.string || this.fields[attrs.name]?.string || attrs.name,
                enableCounters: evaluateBooleanExpr(attrs.enable_counters),
                expand: evaluateBooleanExpr(attrs.expand),
                fieldName: attrs.name,
                icon: _normalizeIconClass(attrs.icon),
                id: nextSectionId++,
                limit: evaluateExpr(attrs.limit || String(DEFAULT_LIMIT)),
                type,
                values: new Map(),
            };
            if (type === "category") {
                section.activeValueId = this.searchPanelDefaults[attrs.name];
                section.icon = section.icon || "fa-solid fa-folder";
                section.hierarchize = evaluateBooleanExpr(attrs.hierarchize || "1");
                section.depth = attrs.depth ? Number.parseInt(attrs.depth, 10) : 0;
                section.values.set(false, {
                    childrenIds: [],
                    display_name: ALL.toString(),
                    id: false,
                    bold: true,
                    parentId: false,
                });
                hasCategoryWithCounters =
                    hasCategoryWithCounters || section.enableCounters;
            } else {
                section.domain = attrs.domain || "[]";
                section.groupBy = attrs.groupby || null;
                section.icon = section.icon || "fa-solid fa-filter";
                hasFilterWithDomain = hasFilterWithDomain || section.domain !== "[]";
            }
            this.sections.push([section.id, section]);
        }

        /**
         * Category counters are auto-disabled when a filter domain exists, to
         * avoid inconsistent counts. Quick fix; a proper solution would rework
         * the search panel's counter computation.
         */
        if (hasCategoryWithCounters && hasFilterWithDomain) {
            for (const section of this.sections) {
                if (section[1].type === "category") {
                    section[1].enableCounters = false;
                }
            }
            console.warn(
                "Warning: categories with counters are incompatible with filters having a domain attribute.",
                "All category counters have been disabled to avoid inconsistencies.",
            );
        }

        return false; // stop the parser from visiting children
    }

    /** Process a `<separator/>` node: flush the current group. */
    visitSeparator() {
        this.pushGroup();
    }
}
