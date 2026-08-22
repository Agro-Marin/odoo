// @ts-check
/** @odoo-module native */

import {
    append,
    combineAttributes,
    createElement,
    extractAttributes,
    getTag,
} from "@web/core/utils/dom/xml";
import { toInterpolatedStringExpression, ViewCompiler } from "@web/views/view_compiler";
import { toStringExpression } from "@web/views/view_utils";

/**
 * @typedef {Object} DropdownDef
 * @property {Element} el
 * @property {boolean} inserted
 * @property {boolean} shouldInsert
 * @property {("dropdown" | "toggler" | "menu")[]} parts
 */

const ACTION_TYPES = ["action", "object"];
const SPECIAL_TYPES = [
    ...ACTION_TYPES,
    "open",
    "delete",
    "url",
    "set_cover",
    "archive",
    "unarchive",
];

export class KanbanCompiler extends ViewCompiler {
    setup() {
        /** @type {any} */ (this).compilers.push(
            { selector: "t[t-call]", fn: this.compileTCall },
            { selector: "img", fn: this.compileImage },
        );
    }

    /**
     * @override
     */
    compileButton(el, params) {
        const type = el.getAttribute("type");
        if (!SPECIAL_TYPES.includes(type)) {
            return super.compileButton(el, params);
        }

        combineAttributes(el, "class", ["oe_kanban_action"]);

        if (ACTION_TYPES.includes(type)) {
            if (!el.hasAttribute("debounce")) {
                el.setAttribute("debounce", 300);
            }
            return super.compileButton(el, params);
        }

        const nodeParams = extractAttributes(el, ["type"]);
        if (type === "set_cover") {
            const { "data-field": fieldName } = extractAttributes(el, ["data-field"]);
            Object.assign(nodeParams, { fieldName });
        }
        const strParams = Object.entries(nodeParams)
            .map(([k, v]) => [k, toStringExpression(v)].join(":"))
            .join(",");
        el.setAttribute("t-on-click", `()=>__comp__.triggerAction({${strParams}})`);

        const compiled = createElement(el.nodeName);
        for (const { name, value } of el.attributes) {
            compiled.setAttribute(name, value);
        }
        if (getTag(el, true) === "a" && !compiled.hasAttribute("href")) {
            compiled.setAttribute("href", "#");
        }
        for (const child of el.childNodes) {
            append(compiled, this.compileNode(child, params));
        }

        return compiled;
    }
    /**
     * @returns {Element}
     */
    compileImage(el) {
        const element = el.cloneNode(true);
        element.setAttribute("loading", "lazy");
        return element;
    }

    /**
     * @override
     */
    compileField(el, params) {
        let compiled;
        const recordExpr = params.recordExpr || "__comp__.props.record";
        const dataPointIdExpr = params.dataPointIdExpr || `${recordExpr}.id`;
        if (!el.hasAttribute("widget")) {
            const fieldId = el.getAttribute("field_id");
            compiled = createElement("span", {
                "t-out":
                    params.formattedValueExpr ||
                    `__comp__.getFormattedValue(${toStringExpression(fieldId)})`,
            });
        } else {
            compiled = super.compileField(el, params);
            const fieldId = el.getAttribute("field_id");
            compiled.setAttribute(
                "id",
                `${toStringExpression(`${fieldId}_`)} + ${dataPointIdExpr}`,
            );
            const readonlyAttr = compiled.getAttribute("readonly");
            if (readonlyAttr) {
                compiled.setAttribute(
                    "readonly",
                    `${recordExpr}.isInEdition || (${readonlyAttr})`,
                );
            } else {
                compiled.setAttribute("readonly", `${recordExpr}.isInEdition`);
            }
        }

        const attrs = {};
        for (const attr of el.attributes) {
            attrs[attr.name] = attr.value;
        }

        if (el.hasAttribute("widget")) {
            const attrsParts = Object.entries(attrs).map(([key, value]) => {
                if (key.startsWith("t-attf-")) {
                    key = key.slice(7);
                    value = toInterpolatedStringExpression(value);
                } else if (key.startsWith("t-att-")) {
                    key = key.slice(6);
                    value = `"" + (${value})`;
                } else if (key.startsWith("t-att")) {
                    throw new Error("t-att on <field> nodes is not supported");
                } else if (!key.startsWith("t-")) {
                    value = toStringExpression(value);
                }
                return `'${key}':${value}`;
            });
            compiled.setAttribute("attrs", `{${attrsParts.join(",")}}`);
        } else {
            for (const [key, value] of Object.entries(attrs)) {
                if (
                    ["class", "style"].includes(key) ||
                    key.startsWith("t-att-") ||
                    key.startsWith("t-attf-")
                ) {
                    compiled.setAttribute(key, value);
                }
            }
        }

        for (const attr of Object.keys(attrs)) {
            if (attr.startsWith("t-") && !attr.startsWith("t-att")) {
                compiled.setAttribute(attr, attrs[attr]);
            }
        }

        return compiled;
    }

    /**
     * @param {Element} el
     * @param {Object} params
     * @returns {Element}
     */
    compileTCall(el, params) {
        const compiled = this.compileGenericNode(el, params);
        const tname = /** @type {string} */ (el.getAttribute("t-call"));
        if (tname in this.templates) {
            compiled.setAttribute(
                "t-call",
                `{{__comp__.templates[${toStringExpression(tname)}]}}`,
            );
        }
        return compiled;
    }
}
/** @type {any} */ (KanbanCompiler).OWL_DIRECTIVE_WHITELIST = [
    .../** @type {any} */ (ViewCompiler).OWL_DIRECTIVE_WHITELIST,
    "t-name",
    "t-esc",
    "t-out",
    "t-set",
    "t-value",
    "t-if",
    "t-else",
    "t-elif",
    "t-foreach",
    "t-as",
    "t-key",
    "t-att.*",
    "t-call",
];
