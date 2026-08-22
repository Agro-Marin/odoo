// @ts-check
/** @odoo-module native */

import { evaluateExpr } from "@web/core/py_js/py";
import { visitXML } from "@web/core/utils/dom/xml";
import { exprToBoolean } from "@web/core/utils/format/strings";
import { parseFieldNode } from "@web/views/field_arch";

import { ViewArchParser } from "../view_arch_parser.js";

const FIELD_ATTRIBUTE_NAMES = [
    "date_start",
    "date_delay",
    "date_stop",
    "all_day",
    "create_name_field",
    "color",
];
const SCALES = ["day", "week", "month", "year"];

class CalendarParseArchError extends Error {}

/**
 * @type {string[]}
 */
const FILTER_ATTRIBUTE_NAMES = [
    "avatar_field",
    "write_model",
    "write_field",
    "color",
    "filters",
];

export class CalendarArchParser extends ViewArchParser {
    /**
     * @param {Element} xmlDoc
     * @param {Object} models
     * @param {string} modelName
     * @returns {Object}
     * @throws {CalendarParseArchError}
     */
    parse(xmlDoc, models, modelName) {
        const fields = models[modelName].fields;
        const root = this.parseRootAttributes(xmlDoc, fields);
        const state = {
            models,
            modelName,
            fields,
            jsClass: root.jsClass,
            fieldNames: root.fieldNames,
            /** @type {Record<string, any>} */
            popoverFieldNodes: {},
            /** @type {Record<string, any>} */
            filtersInfo: {},
        };

        visitXML(xmlDoc, (node) => {
            if (node.tagName === "field") {
                this.parseFieldNodeInArch(node, state);
            }
        });

        this.validate(root);

        return {
            aggregate: root.aggregate,
            canCreate: root.canCreate,
            canDelete: root.canDelete,
            canEdit: root.canEdit,
            eventLimit: root.eventLimit,
            fieldMapping: root.fieldMapping,
            fieldNames: [...state.fieldNames],
            filtersInfo: state.filtersInfo,
            formViewId: root.formViewId,
            hasEditDialog: root.hasEditDialog,
            multiCreateView: root.multiCreateView,
            quickCreate: root.quickCreate,
            quickCreateViewId: root.quickCreateViewId,
            isDateHidden: root.isDateHidden,
            isTimeHidden: root.isTimeHidden,
            monthOverflow: root.monthOverflow,
            popoverFieldNodes: state.popoverFieldNodes,
            scale: root.scale,
            scales: root.scales,
            showUnusualDays: root.showUnusualDays,
            showDatePicker: root.showDatePicker,
        };
    }

    /**
     * @param {Element} xmlDoc
     * @param {Record<string, any>} fields
     * @returns {Record<string, any>}
     */
    parseRootAttributes(xmlDoc, fields) {
        /** @type {Record<string, string>} */
        const fieldMapping = {};
        /** @type {Set<string>} */
        const fieldNames = new Set(fields.display_name ? ["display_name"] : []);
        for (const fieldAttrName of FIELD_ATTRIBUTE_NAMES) {
            if (xmlDoc.hasAttribute(fieldAttrName)) {
                const fieldName = /** @type {string} */ (
                    xmlDoc.getAttribute(fieldAttrName)
                );
                fieldNames.add(fieldName);
                fieldMapping[fieldAttrName] = fieldName;
            }
        }
        const aggregate = xmlDoc.getAttribute("aggregate") || null;
        if (aggregate) {
            fieldNames.add(aggregate.split(":")[0]);
        }

        const scalesAttr = xmlDoc.getAttribute("scales");
        const scales = scalesAttr
            ? scalesAttr
                  .split(",")
                  .map((scale) => scale.trim())
                  .filter((scale) => SCALES.includes(scale))
            : [...SCALES];
        const scale = xmlDoc.hasAttribute("mode")
            ? xmlDoc.getAttribute("mode")
            : scales.includes("week")
              ? "week"
              : scales[0];

        const quickCreate = exprToBoolean(xmlDoc.getAttribute("quick_create"), true);
        return {
            fieldMapping,
            fieldNames,
            aggregate,
            scales,
            scale,
            quickCreate,
            canCreate: exprToBoolean(xmlDoc.getAttribute("create"), true),
            canDelete: exprToBoolean(xmlDoc.getAttribute("delete"), true),
            canEdit: exprToBoolean(xmlDoc.getAttribute("edit"), true),
            eventLimit: xmlDoc.hasAttribute("event_limit")
                ? evaluateExpr(
                      /** @type {string} */ (xmlDoc.getAttribute("event_limit")),
                  )
                : 5,
            formViewId:
                Number.parseInt(
                    /** @type {string} */ (xmlDoc.getAttribute("form_view_id")),
                    10,
                ) || false,
            hasEditDialog: exprToBoolean(xmlDoc.getAttribute("event_open_popup")),
            isDateHidden: exprToBoolean(xmlDoc.getAttribute("hide_date")),
            isTimeHidden: exprToBoolean(xmlDoc.getAttribute("hide_time")),
            jsClass: xmlDoc.getAttribute("js_class") || null,
            monthOverflow: exprToBoolean(xmlDoc.getAttribute("month_overflow"), true),
            multiCreateView: xmlDoc.getAttribute("multi_create_view"),
            quickCreateViewId:
                (quickCreate &&
                    Number.parseInt(
                        /** @type {string} */ (
                            xmlDoc.getAttribute("quick_create_view_id")
                        ),
                        10,
                    )) ||
                null,
            showDatePicker: exprToBoolean(
                xmlDoc.getAttribute("show_date_picker"),
                true,
            ),
            showUnusualDays: exprToBoolean(xmlDoc.getAttribute("show_unusual_days")),
        };
    }

    /**
     * @param {Element} node
     * @param {Record<string, any>} state
     */
    parseFieldNodeInArch(node, state) {
        const fieldName = /** @type {string} */ (node.getAttribute("name"));
        state.fieldNames.add(fieldName);
        const fieldInfo = parseFieldNode(
            node,
            state.models,
            state.modelName,
            "calendar",
            state.jsClass,
        );
        state.popoverFieldNodes[fieldName] = fieldInfo;

        if (node.hasAttribute("invisible") && !node.hasAttribute("filters")) {
            return;
        }
        if (!FILTER_ATTRIBUTE_NAMES.some((attr) => node.hasAttribute(attr))) {
            return;
        }
        state.filtersInfo[fieldName] = this.buildFilterInfo(node, fieldName, {
            field: state.fields[fieldName],
            context: fieldInfo.context || "{}",
            previous: state.filtersInfo[fieldName],
        });
    }

    /**
     * @param {Element} node
     * @param {string} fieldName
     * @param {{ field: any, context: string, previous?: any }} params
     * @returns {Record<string, any>}
     */
    buildFilterInfo(node, fieldName, { field, context, previous }) {
        const filterInfo = previous || {
            avatarFieldName: null,
            colorFieldName: null,
            context,
            fieldName,
            filterFieldName: null,
            label: field.string,
            resModel: field.relation,
            writeFieldName: null,
            writeResModel: null,
        };
        filterInfo.avatarFieldName = node.getAttribute("avatar_field") || null;
        filterInfo.colorFieldName =
            (node.hasAttribute("filters") && node.getAttribute("color")) || null;
        filterInfo.filterFieldName = node.getAttribute("filter_field") || null;
        filterInfo.writeFieldName = node.getAttribute("write_field") || null;
        filterInfo.writeResModel = node.getAttribute("write_model") || null;
        return filterInfo;
    }

    /**
     * @param {Record<string, any>} root
     * @throws {CalendarParseArchError}
     */
    validate(root) {
        if (!root.fieldMapping.date_start) {
            throw new CalendarParseArchError(
                `Calendar view must define "date_start" attribute.`,
            );
        }
        if (!root.scales.includes(root.scale)) {
            throw new CalendarParseArchError(
                `Calendar view cannot display mode: ${root.scale}`,
            );
        }
        if (!Number.isInteger(root.eventLimit)) {
            throw new CalendarParseArchError(
                `Calendar view's event limit should be a number`,
            );
        }
    }
}
