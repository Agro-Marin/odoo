// @ts-check
/** @odoo-module native */

import { exprToBoolean } from "@web/core/utils/format/strings";
import { GROUPABLE_TYPES } from "@web/search/utils/misc";
import {
    requiredAttribute,
    staticModifier,
    ViewArchParser,
} from "@web/views/view_arch_parser";

const MODES = ["bar", "line", "pie", "scatter"];
const ORDERS = ["ASC", "DESC", "asc", "desc", null];

export class GraphArchParser extends ViewArchParser {
    /**
     * @param {Element} arch
     * @param {Record<string, any>} [models]
     * @param {string} [modelName]
     * @returns {{
     * fields: Object,
     * fieldAttrs: Object,
     * groupBy: string[],
     * measures: string[],
     * measure?: string,
     * mode?: string,
     * order?: string,
     * title?: string,
     * stacked?: boolean,
     * cumulated?: boolean,
     * cumulatedStart?: boolean,
     * disableLinking?: boolean,
     * }}
     */
    parse(arch, models, modelName) {
        const fields = (modelName && models?.[modelName]?.fields) || {};
        return this.visitArch(
            arch,
            /** @type {any} */ ({ fields, fieldAttrs: {}, groupBy: [], measures: [] }),
            { graph: this.parseRootNode, field: this.parseFieldNode },
        );
    }

    /**
     * @param {Element} node
     * @param {any} archInfo
     */
    parseRootNode(node, archInfo) {
        for (const [attr, key] of [
            ["disable_linking", "disableLinking"],
            ["stacked", "stacked"],
            ["cumulated", "cumulated"],
            ["cumulated_start", "cumulatedStart"],
        ]) {
            if (node.hasAttribute(attr)) {
                archInfo[key] = exprToBoolean(node.getAttribute(attr));
            }
        }
        const mode = node.getAttribute("type");
        if (mode && MODES.includes(mode)) {
            archInfo.mode = mode;
        }
        const order = node.getAttribute("order");
        if (order && ORDERS.includes(order)) {
            archInfo.order = order.toUpperCase();
        }
        const title = node.getAttribute("string");
        if (title) {
            archInfo.title = title;
        }
    }

    /**
     * @param {Element} node
     * @param {any} archInfo
     */
    parseFieldNode(node, archInfo) {
        const fieldName = requiredAttribute(node, "name");
        if (fieldName === "id") {
            return;
        }
        /**
         * @param {string} key
         * @param {any} value
         */
        const setAttr = (key, value) => {
            archInfo.fieldAttrs[fieldName] ??= {};
            archInfo.fieldAttrs[fieldName][key] = value;
        };

        const string = node.getAttribute("string");
        if (string) {
            setAttr("string", string);
        }
        const widget = node.getAttribute("widget");
        if (widget) {
            setAttr("widget", widget);
        }
        const invisible = node.getAttribute("invisible");
        const hidden = staticModifier(invisible);
        if (hidden) {
            setAttr("isInvisible", true);
            return;
        }
        if (hidden === undefined) {
            setAttr("invisible", invisible);
        }

        if (node.getAttribute("type") === "measure") {
            archInfo.measures.push(fieldName);
            archInfo.measure = fieldName;
            return;
        }
        const { type } = archInfo.fields[fieldName];
        if (GROUPABLE_TYPES.includes(type)) {
            const interval = node.getAttribute("interval");
            archInfo.groupBy.push(interval ? `${fieldName}:${interval}` : fieldName);
        }
    }
}
