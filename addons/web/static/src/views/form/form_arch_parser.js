// @ts-check
/** @odoo-module native */

import { visitXML } from "@web/core/utils/dom/xml";
import { exprToBoolean } from "@web/core/utils/format/strings";
import { parseFieldNode } from "@web/views/field_arch";
import { getActiveActions } from "@web/views/view_utils";
import { Widget } from "@web/views/widgets/widget";

import { ViewArchParser } from "../view_arch_parser.js";

export class FormArchParser extends ViewArchParser {
    /**
     * @param {Element} xmlDoc
     * @param {Object} models
     * @param {string} modelName
     * @returns {{ activeActions: Object, autofocusFieldIds: string[], disableAutofocus: boolean, fieldNodes: Object, widgetNodes: Object, xmlDoc: Element }}
     */
    parse(xmlDoc, models, modelName) {
        const jsClass = xmlDoc.getAttribute("js_class");
        const disableAutofocus = exprToBoolean(
            xmlDoc.getAttribute("disable_autofocus") || "",
        );
        const activeActions = getActiveActions(xmlDoc);
        const fieldNodes = {};
        const widgetNodes = {};
        let widgetNextId = 0;
        const fieldNextIds = {};
        const autofocusFieldIds = [];
        visitXML(xmlDoc, (node) => {
            if (node.tagName === "field") {
                const fieldInfo = parseFieldNode(
                    node,
                    models,
                    modelName,
                    "form",
                    jsClass ?? undefined,
                );
                if (!(fieldInfo.name in fieldNextIds)) {
                    fieldNextIds[fieldInfo.name] = 0;
                }
                const fieldId = `${fieldInfo.name}_${fieldNextIds[fieldInfo.name]++}`;
                fieldNodes[fieldId] = fieldInfo;
                node.setAttribute("field_id", fieldId);
                if (exprToBoolean(node.getAttribute("default_focus") || "")) {
                    autofocusFieldIds.push(fieldId);
                }
                if (fieldInfo.type === "properties") {
                    /** @type {any} */ (activeActions).addPropertyFieldValue = true;
                }
                return false;
            } else if (node.tagName === "widget") {
                const widgetInfo = Widget.parseWidgetNode(node);
                const widgetId = `widget_${++widgetNextId}`;
                widgetNodes[widgetId] = widgetInfo;
                node.setAttribute("widget_id", widgetId);
            }
        });
        return {
            activeActions,
            autofocusFieldIds,
            disableAutofocus,
            fieldNodes,
            widgetNodes,
            xmlDoc,
        };
    }
}
