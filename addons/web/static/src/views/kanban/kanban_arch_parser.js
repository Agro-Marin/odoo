// @ts-check
/** @odoo-module native */

import { extractAttributes, visitXML } from "@web/core/utils/dom/xml";
import { exprToBoolean } from "@web/core/utils/format/strings";
import { stringToOrderBy } from "@web/core/utils/order_by";
import { parseFieldNode } from "@web/views/field_arch";
import { requiredAttribute, ViewArchParser } from "@web/views/view_arch_parser";
import { getActiveActions } from "@web/views/view_utils";

export const KANBAN_CARD_ATTRIBUTE = "card";
export const KANBAN_MENU_ATTRIBUTE = "menu";

export class KanbanArchParser extends ViewArchParser {
    /**
     * @typedef {{
     * xmlDoc: Element,
     * models: Record<string, any>,
     * modelName: string,
     * jsClass: string | undefined,
     * templateDocs: Record<string, any>,
     * headerButtons: any[],
     * controls: any[],
     * fieldNodes: Record<string, any>,
     * fieldNextIds: Record<string, number>,
     * widgetNodes: Record<string, any>,
     * widgetNextId: number,
     * tooltipInfo: Record<string, any>,
     * handleField: string | null,
     * }} KanbanParseState
     */

    /**
     * @param {Element} xmlDoc
     * @returns {{
     * activeActions: any,
     * className: string | null,
     * canOpenRecords: boolean,
     * defaultOrder: any[],
     * limit: string | null,
     * countLimit: string | null,
     * recordsDraggable: boolean,
     * groupsDraggable: boolean,
     * defaultGroupBy: string[] | null,
     * onCreate: string | null,
     * quickCreateView: string | null,
     * openAction: { action: string, type: string } | null,
     * }}
     */
    parseRootAttributes(xmlDoc) {
        /** @type {any} */
        const activeActions = getActiveActions(xmlDoc);
        activeActions.archiveGroup = exprToBoolean(
            xmlDoc.getAttribute("archivable"),
            true,
        );
        activeActions.createGroup = exprToBoolean(
            xmlDoc.getAttribute("group_create"),
            true,
        );
        activeActions.deleteGroup = exprToBoolean(
            xmlDoc.getAttribute("group_delete"),
            true,
        );
        activeActions.editGroup = exprToBoolean(
            xmlDoc.getAttribute("group_edit"),
            true,
        );
        activeActions.quickCreate =
            activeActions.create &&
            exprToBoolean(xmlDoc.getAttribute("quick_create"), true);

        const action = xmlDoc.getAttribute("action");
        const type = xmlDoc.getAttribute("type");
        return {
            activeActions,
            className: xmlDoc.getAttribute("class") || null,
            canOpenRecords: exprToBoolean(xmlDoc.getAttribute("can_open"), true),
            defaultOrder: stringToOrderBy(xmlDoc.getAttribute("default_order") || null),
            limit: xmlDoc.getAttribute("limit"),
            countLimit: xmlDoc.getAttribute("count_limit"),
            recordsDraggable: exprToBoolean(
                xmlDoc.getAttribute("records_draggable"),
                true,
            ),
            groupsDraggable: exprToBoolean(
                xmlDoc.getAttribute("groups_draggable"),
                true,
            ),
            defaultGroupBy: xmlDoc.hasAttribute("default_group_by")
                ? /** @type {string} */ (xmlDoc.getAttribute("default_group_by")).split(
                      ",",
                  )
                : null,
            onCreate: xmlDoc.getAttribute("on_create"),
            quickCreateView: xmlDoc.getAttribute("quick_create_view"),
            openAction: action && type ? { action, type } : null,
        };
    }

    /**
     * @param {Element} xmlDoc
     * @param {Record<string, any>} models
     * @param {string} modelName
     * @returns {KanbanParseState}
     */
    newParseState(xmlDoc, models, modelName) {
        return {
            xmlDoc,
            models,
            modelName,
            jsClass: xmlDoc.getAttribute("js_class") ?? undefined,
            templateDocs: {},
            headerButtons: [],
            controls: [],
            fieldNodes: {},
            fieldNextIds: {},
            widgetNodes: {},
            widgetNextId: 0,
            tooltipInfo: {},
            handleField: null,
        };
    }

    /**
     * @param {Element} node
     * @param {KanbanParseState} state
     * @returns {false | undefined}
     */
    visitNode(node, state) {
        if (node.hasAttribute("t-name")) {
            state.templateDocs[/** @type {string} */ (node.getAttribute("t-name"))] =
                node;
            return undefined;
        }
        switch (node.tagName) {
            case "header":
                state.headerButtons = this.parseHeaderButtons(node);
                return false;
            case "control":
                state.controls.push(...this.parseControls(node));
                return false;
            case "field":
                return this.parseFieldNodeInArch(node, state);
            case "widget":
                return this.parseWidgetNodeInArch(node, state);
            case "img":
                return this.parseImageNode(node, state);
            default:
                return undefined;
        }
    }

    /**
     * @param {Element} node
     * @param {KanbanParseState} state
     * @returns {undefined}
     */
    parseFieldNodeInArch(node, state) {
        const { models, modelName } = state;
        const fieldName = requiredAttribute(node, "name");
        const field = models[modelName].fields[fieldName];
        if (!field) {
            throw new Error(
                `Kanban arch parsing error: <field name="${fieldName}"/> does not exist on model "${modelName}"`,
            );
        }
        const widget = node.getAttribute("widget");
        if (!widget && field.type === "many2many") {
            node.setAttribute("widget", "many2many_tags");
        }
        const fieldInfo = parseFieldNode(
            node,
            models,
            modelName,
            "kanban",
            state.jsClass,
        );
        const name = fieldInfo.name;
        if (!(fieldInfo.name in state.fieldNextIds)) {
            state.fieldNextIds[fieldInfo.name] = 0;
        }
        const fieldId = `${fieldInfo.name}_${state.fieldNextIds[fieldInfo.name]++}`;
        state.fieldNodes[fieldId] = fieldInfo;
        node.setAttribute("field_id", fieldId);
        if (fieldInfo.options.group_by_tooltip) {
            state.tooltipInfo[name] = fieldInfo.options.group_by_tooltip;
        }
        if (fieldInfo.isHandle) {
            state.handleField = name;
        }
        return undefined;
    }

    /**
     * @param {Element} node
     * @param {KanbanParseState} state
     * @returns {undefined}
     */
    parseWidgetNodeInArch(node, state) {
        const widgetInfo = this.parseWidgetNode(node);
        const widgetId = `widget_${++state.widgetNextId}`;
        state.widgetNodes[widgetId] = widgetInfo;
        node.setAttribute("widget_id", widgetId);
        return undefined;
    }

    /**
     * @param {Element} node
     * @param {KanbanParseState} state
     * @returns {undefined}
     */
    parseImageNode(node, state) {
        const attSrc = node.getAttribute("t-att-src");
        if (
            attSrc &&
            /\bkanban_image\b/.test(attSrc) &&
            !Object.values(state.fieldNodes).some((f) => f.name === "write_date")
        ) {
            state.fieldNodes.write_date_0 = {
                name: "write_date",
                type: "datetime",
            };
        }
        return undefined;
    }

    /**
     * @param {Element} xmlDoc
     * @param {Object} models
     * @param {string} modelName
     * @returns {{
     * activeActions: Object,
     * canOpenRecords: boolean,
     * cardClassName: string,
     * cardColorField: string | null,
     * className: string | null,
     * controls: Object[],
     * defaultGroupBy: string[] | null,
     * fieldNodes: Object,
     * widgetNodes: Object,
     * handleField: string | null,
     * headerButtons: Object[],
     * defaultOrder: Object[],
     * onCreate: string | null,
     * openAction: { action: string, type: string } | null,
     * quickCreateView: string | null,
     * recordsDraggable: boolean,
     * groupsDraggable: boolean,
     * limit: number | null,
     * countLimit: number | null,
     * progressAttributes: Object | false,
     * templateDocs: Object,
     * tooltipInfo: Object,
     * examples: string | null,
     * xmlDoc: Element,
     * }}
     */
    parse(xmlDoc, models, modelName) {
        const root = this.parseRootAttributes(xmlDoc);
        const state = this.newParseState(xmlDoc, models, modelName);
        visitXML(xmlDoc, (node) => this.visitNode(node, state));

        /** @type {any} */
        let progressAttributes = false;
        const progressBar = xmlDoc.querySelector("progressbar");
        if (progressBar) {
            progressAttributes = this.parseProgressBar(
                progressBar,
                models[modelName].fields,
            );
        }

        const cardDoc = state.templateDocs[KANBAN_CARD_ATTRIBUTE];
        if (!cardDoc) {
            throw new Error(`Missing '${KANBAN_CARD_ATTRIBUTE}' template.`);
        }

        let { defaultOrder } = root;
        if (!defaultOrder.length && state.handleField) {
            defaultOrder = stringToOrderBy(`${state.handleField}, id`);
        }

        const { limit, countLimit } = root;
        return {
            ...root,
            defaultOrder,
            cardClassName: cardDoc.getAttribute("class") || "",
            cardColorField: xmlDoc.getAttribute("highlight_color"),
            controls: state.controls,
            fieldNodes: state.fieldNodes,
            widgetNodes: state.widgetNodes,
            handleField: state.handleField,
            headerButtons: state.headerButtons,
            limit: limit ? Number.parseInt(limit, 10) : null,
            countLimit: countLimit ? Number.parseInt(countLimit, 10) : null,
            progressAttributes,
            templateDocs: state.templateDocs,
            tooltipInfo: state.tooltipInfo,
            examples: xmlDoc.getAttribute("examples"),
            xmlDoc,
        };
    }

    /**
     * @param {Element} progressBar
     * @param {Object} fields
     * @returns {{ fieldName: string, colors: Object, sumField: Object | false, help: string }}
     */
    parseProgressBar(progressBar, fields) {
        const attrs = extractAttributes(progressBar, [
            "field",
            "colors",
            "sum_field",
            "help",
        ]);
        let colors;
        try {
            colors = JSON.parse(attrs.colors);
        } catch (error) {
            throw new Error(
                `Kanban arch parsing error: invalid "colors" attribute on <progressbar/> (must be a JSON object mapping field values to color names): ${error.message}`,
                { cause: error },
            );
        }
        return {
            fieldName: attrs.field,
            colors,
            sumField: fields[attrs.sum_field] || false,
            help: attrs.help,
        };
    }
}
