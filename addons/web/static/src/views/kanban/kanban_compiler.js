// @ts-check
/** @odoo-module native */

/** @module @web/views/kanban/kanban_compiler - Template compiler transforming kanban card/menu arch into OWL-compatible templates */

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

/**
 * Neutralise ``${...}`` in a raw arch string before it is wrapped as a
 * template-literal props expression by ``toStringExpression``. That helper only
 * escapes backticks, so a ``${`` sequence would survive and be evaluated as JS
 * interpolation in the component scope. Arch authors are privileged (this is
 * defense-in-depth, not an escalation fix), but literal ``${...}`` text in an
 * arch attribute must render verbatim rather than execute.
 *
 * @param {string} [value]
 * @returns {string}
 */
function escapeStringInterpolation(value) {
    return (value ?? "").replaceAll("${", "\\${");
}

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

/**
 * Template compiler for kanban card/menu templates: wires action buttons
 * (open, delete, set_cover, archive, url) to `triggerAction()`, renders
 * widget-less fields as `<span>`, lazy-loads images, and resolves `t-call`
 * against compiled template refs.
 */
export class KanbanCompiler extends ViewCompiler {
    setup() {
        /** @type {any} */ (this).compilers.push(
            { selector: "t[t-call]", fn: this.compileTCall },
            { selector: "img", fn: this.compileImage },
        );
    }

    // Compilers

    /**
     * @override
     */
    compileButton(el, params) {
        const type = el.getAttribute("type");
        if (!SPECIAL_TYPES.includes(type)) {
            // Not a kanban-specific action type.
            return super.compileButton(el, params);
        }

        combineAttributes(el, "class", ["oe_kanban_action"]);

        if (ACTION_TYPES.includes(type)) {
            if (!el.hasAttribute("debounce")) {
                // action buttons are debounced in kanban records
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
            .map(([k, v]) =>
                [k, toStringExpression(escapeStringInterpolation(v))].join(":"),
            )
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
            // fields without a specified widget are rendered as simple spans in kanban records
            const fieldId = el.getAttribute("field_id");
            compiled = createElement("span", {
                "t-out":
                    params.formattedValueExpr ||
                    `__comp__.getFormattedValue("${fieldId}")`,
            });
        } else {
            compiled = super.compileField(el, params);
            const fieldId = el.getAttribute("field_id");
            compiled.setAttribute("id", `'${fieldId}_' + ${dataPointIdExpr}`);
            // x2many kanban records can be edited in a dialog using the same
            // record; force fields readonly while it's in edition so the
            // background kanban doesn't show it being edited.
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
                    value = toStringExpression(escapeStringInterpolation(value));
                }
                return `'${key}':${value}`;
            });
            compiled.setAttribute("attrs", `{${attrsParts.join(",")}}`);
        } else if (odoo.debug) {
            // Widget-less fields compile to a bare <span t-out=...>: only t-*
            // directives (except t-att*) are forwarded below, so class/style
            // and t-att(f)-* attributes are silently dropped. Surface that in
            // debug mode instead of leaving arch authors to diff the DOM.
            for (const attr of Object.keys(attrs)) {
                if (
                    ["class", "style"].includes(attr) ||
                    attr.startsWith("t-att-") ||
                    attr.startsWith("t-attf-")
                ) {
                    console.warn(
                        `KanbanCompiler: attribute "${attr}" on <field name="${attrs.name}"/> is ignored because the field has no widget (add a widget="..." to forward it)`,
                    );
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
        const tname = el.getAttribute("t-call");
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
