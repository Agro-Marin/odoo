// @ts-check
/** @odoo-module native */

import { evaluateExpr } from "@web/core/py_js/py";
import { exprToBoolean } from "@web/core/utils/format/strings";
import {
    requiredAttribute,
    staticModifier,
    ViewArchParser,
} from "@web/views/view_arch_parser";
/**
 * @type {string[]}
 */
const PIVOT_FIELD_ATTRS = ["name", "type", "operator", "interval", "string", "widget"];

export class PivotArchParser extends ViewArchParser {
    /**
     * @param {Element} arch
     * @returns {{
     * activeMeasures: string[],
     * colGroupBys: string[],
     * defaultOrder: string | null,
     * fieldAttrs: Object,
     * rowGroupBys: string[],
     * widgets: Object,
     * title?: string,
     * disableLinking?: boolean,
     * displayQuantity?: boolean,
     * }}
     */
    parse(arch, _models, _modelName) {
        return this.visitArch(
            arch,
            /** @type {any} */ ({
                activeMeasures: [],
                colGroupBys: [],
                defaultOrder: null,
                fieldAttrs: {},
                rowGroupBys: [],
                widgets: {},
            }),
            { pivot: this.parseRootNode, field: this.parseFieldNode },
        );
    }

    /**
     * @param {Element} node
     * @param {any} archInfo
     */
    parseRootNode(node, archInfo) {
        if (node.hasAttribute("disable_linking")) {
            archInfo.disableLinking = exprToBoolean(
                node.getAttribute("disable_linking"),
            );
        }
        if (node.hasAttribute("default_order")) {
            archInfo.defaultOrder = node.getAttribute("default_order");
        }
        if (node.hasAttribute("string")) {
            archInfo.title = node.getAttribute("string");
        }
        if (node.hasAttribute("display_quantity")) {
            archInfo.displayQuantity = exprToBoolean(
                node.getAttribute("display_quantity"),
            );
        }
    }

    /**
     * @param {Element} node
     * @param {any} archInfo
     */
    parseFieldNode(node, archInfo) {
        const name = requiredAttribute(node, "name");
        const attrs = (archInfo.fieldAttrs[name] ??= {});
        if (node.hasAttribute("string")) {
            attrs.string = node.getAttribute("string");
        }
        if (staticModifier(node.getAttribute("invisible"))) {
            attrs.isInvisible = true;
            return;
        }
        for (const attribute of node.attributes) {
            if (PIVOT_FIELD_ATTRS.includes(attribute.name)) {
                continue;
            }
            attrs[attribute.name] =
                attribute.name === "options"
                    ? evaluateExpr(attribute.value)
                    : attribute.value;
        }

        const interval = node.getAttribute("interval");
        const groupBy = interval ? `${name}:${interval}` : name;
        if (node.hasAttribute("widget")) {
            archInfo.widgets[groupBy] = node.getAttribute("widget");
        }
        const type = node.getAttribute("type");
        if (type === "measure" || node.hasAttribute("operator")) {
            archInfo.activeMeasures.push(groupBy);
        }
        if (type === "col") {
            archInfo.colGroupBys.push(groupBy);
        }
        if (type === "row") {
            archInfo.rowGroupBys.push(groupBy);
        }
    }
}
