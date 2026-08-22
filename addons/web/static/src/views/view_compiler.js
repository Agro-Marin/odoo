// @ts-check
/** @odoo-module native */

/**
 * @typedef Compiler
 * @property {string} selector
 * @property {(el: Element, params: Record<string, any>) => Element} fn
 * @property {string} [class]
 * @property {boolean} [doNotCopyAttributes]
 * @property {number} [sequence]
 * @property {boolean} [builtIn]
 */
import { App } from "@odoo/owl";
import {
    append,
    combineAttributes,
    createElement,
    createTextNode,
    getTag,
} from "@web/core/utils/dom/xml";
import { cyrb53, exprToBoolean } from "@web/core/utils/format/strings";

import {
    MODAL_TARGET_ATTRS,
    NOT_SELF_HANDLED,
    SELF_HANDLED_ATTR,
    selfHandledSelector,
} from "./self_handled.js";
import { BUTTON_CLICK_PARAMS, BUTTON_MODIFIERS } from "./view_buttons.js";
import { toStringExpression } from "./view_utils.js";
const BUTTON_STRING_PROPS = ["string", "size", "title", "icon", "id"];
const INTERP_OPENERS = { "{{": "}}", "#{": "}" };

const MODIFIER_ATTRS = ["column_invisible", "invisible", "readonly", "required"];

const NOT_SELF_COMPILING_TAG =
    ":not(field):not(widget):not(button):not(a[type]):not(a[data-type])";

const DROPDOWN_CONTAINER_SELECTOR = [
    ".dropdown",
    ".dropup",
    ".dropend",
    ".dropstart",
    ".btn-group",
    ".btn-group-vertical",
]
    .map((positioning) => `${positioning}${NOT_SELF_COMPILING_TAG}`)
    .join(",");
const DROPDOWN_TOGGLE_SELECTOR = selfHandledSelector("dropdown");

const ARCH_DIALOG_KEY_ATTR = "data-arch-dialog";
const MODAL_TRIGGER_SELECTOR = selfHandledSelector("modal")
    .split(",")
    .flatMap((control) => MODAL_TARGET_ATTRS.map((attr) => `${control}[${attr}]`))
    .join(",");
const MODAL_DISMISS_SELECTOR = '[data-modal-dismiss],[data-bs-dismiss="modal"]';
const ARCH_DIALOGS_EXPR = "__comp__.archDialogs";

export const DEFAULT_COMPILER_SEQUENCE = 50;

/**
 * @param {string} str
 * @param {number} start
 * @param {string} opener
 * @returns {{ expr: string, end: number }}
 */
function findInterpolationEnd(str, start, opener) {
    const closer = INTERP_OPENERS[opener];
    /**
     * @type {string[]}
     */
    const stack = [];
    let depth = 0;
    let i = start + opener.length;
    while (i < str.length) {
        const char = str[i];
        const context = stack.at(-1);
        if (context && context !== "${") {
            if (char === "\\") {
                i += 2;
            } else if (char === context) {
                stack.pop();
                i++;
            } else if (context === "`" && char === "$" && str[i + 1] === "{") {
                stack.push("${");
                i += 2;
            } else {
                i++;
            }
            continue;
        }
        if (char === "'" || char === '"' || char === "`") {
            stack.push(char);
        } else if (char === "{") {
            depth++;
        } else if (char === "}") {
            if (context === "${") {
                stack.pop();
            } else if (depth > 0) {
                depth--;
            } else if (str.startsWith(closer, i)) {
                return {
                    expr: str.slice(start + opener.length, i),
                    end: i + closer.length,
                };
            }
        }
        i++;
    }
    throw new Error(
        `Unterminated "${opener}" interpolation in ${JSON.stringify(str)}: ` +
            `expected a matching "${closer}"`,
    );
}

/**
 * @param {string} str
 * @returns {string}
 */
export function toInterpolatedStringExpression(str) {
    const parts = [];
    let cursor = 0;
    let i = 0;
    while (i < str.length) {
        const opener = Object.keys(INTERP_OPENERS).find((o) => str.startsWith(o, i));
        if (!opener) {
            i++;
            continue;
        }
        const { expr, end } = findInterpolationEnd(str, i, opener);
        if (i > cursor) {
            parts.push(toStringExpression(str.slice(cursor, i)));
        }
        parts.push(`(${expr})`);
        cursor = end;
        i = end;
    }
    parts.push(toStringExpression(str.slice(cursor)));
    return parts.join("+");
}

/**
 * @param {Element} el
 * @param {string} attr
 * @param {string} string
 */
export function appendAttr(el, attr, string) {
    const attrKey = `t-att-${attr}`;
    const attrVal = el.getAttribute(attrKey);
    el.setAttribute(
        attrKey,
        appendToStringifiedObject(/** @type {string} */ (attrVal), string),
    );
}

/**
 * @param {string} originalTattr
 * @param {string} string
 * @returns {string}
 */
function appendToStringifiedObject(originalTattr, string) {
    const re = /{(.*)}/;
    const oldString = re.exec(originalTattr);

    if (oldString) {
        string = `${oldString[1]},${string}`;
    }
    return `{${string}}`;
}

/**
 * @param {Element} target
 * @param {...Element} sources
 * @returns {Element}
 */
function assignOwlDirectives(target, ...sources) {
    for (const source of sources) {
        for (const { name, value } of source.attributes) {
            if (name.startsWith("t-attf-")) {
                const propName = name.slice(7);
                const interpolatedExpression = toInterpolatedStringExpression(value);
                target.setAttribute(propName, interpolatedExpression);
            } else if (name.startsWith("t-att-")) {
                const propName = name.slice(6);
                target.setAttribute(propName, value);
            } else if (name.startsWith("t-")) {
                target.setAttribute(name, value);
            }
        }
    }
    return target;
}

/**
 * @param {Element} el
 * @param {Element} compiled
 */
export function copyAttributes(el, compiled) {
    const isComponent = isComponentNode(compiled);
    const classes = el.className;
    if (classes) {
        if (isComponent) {
            const cls = compiled.className;
            compiled.setAttribute(
                "class",
                cls
                    ? `${toStringExpression(classes + " ")} + ${cls}`
                    : toStringExpression(classes),
            );
        } else {
            compiled.classList.add(...classes.split(/\s+/).filter(Boolean));
        }
    }

    let att = el.getAttribute("style");
    if (att) {
        if (isComponent) {
            att = toStringExpression(att);
        }
        compiled.setAttribute("style", att);
    }
}

/**
 * @param {Object} obj
 * @return {string}
 */
export function encodeObjectForTemplate(obj) {
    return `"${encodeURI(JSON.stringify(obj))}"`;
}

/**
 * @param {Element} el
 * @param {string} modifierName
 * @returns {string | null}
 */
export function getModifier(el, modifierName) {
    return el.getAttribute(modifierName);
}

/**
 * @param {any} node
 * @returns {string}
 */
function getTitleTag(node) {
    return getTag(node)[0].toUpperCase() + getTag(node).slice(1);
}

/**
 * @param {Node} node
 * @returns {boolean}
 */
function isComment(node) {
    return node.nodeType === 8;
}

/**
 * @param {Element} el
 * @returns {boolean}
 */
export function isComponentNode(el) {
    return (
        getTag(el) === getTitleTag(el) ||
        (getTag(el, true) === "t" && "t-component" in el.attributes)
    );
}

/**
 * @param {Node} node
 * @returns {boolean}
 */
export function isTextNode(node) {
    return node.nodeType === 3;
}

/**
 * @param {string | null} title
 * @returns {Element}
 */
export function makeSeparator(title) {
    const separator = createElement("div");
    separator.className =
        "o_horizontal_separator mt-4 mb-3 text-uppercase fw-bolder small";
    separator.textContent = title;
    return separator;
}

/**
 * @param {string | null | undefined} invisible
 * @param {string} [recordExpr]
 * @returns {string}
 */
export function makeIsVisibleExpr(invisible, recordExpr = "__comp__.props.record") {
    if (!invisible || invisible === "False" || invisible === "0") {
        return "true";
    }
    if (invisible === "True" || invisible === "1") {
        return "false";
    }
    return `!__comp__.evaluateBooleanExpr(${JSON.stringify(
        invisible,
    )},${recordExpr}.evalContextWithVirtualIds)`;
}

/**
 * @type {Set<string>}
 */
const warnedShadowedSelectors = new Set();

/**
 * @type {Set<string>}
 */
const shadowedCompilerReports = new Set();

export function getShadowedCompilerReports() {
    return [...shadowedCompilerReports].map((entry) => JSON.parse(entry));
}

export class ViewCompiler {
    /**
     * @type {string[]}
     */
    static OWL_DIRECTIVE_WHITELIST = [];

    constructor(templates) {
        /** @type {number} */
        this.id = 1;
        /** @type {Compiler[]} */
        this.compilers = [
            {
                selector: `[${ARCH_DIALOG_KEY_ATTR}]:not(.modal)`,
                fn: this.compileModalControl,
                doNotCopyAttributes: true,
            },
            {
                selector: ".modal",
                fn: this.compileModal,
                doNotCopyAttributes: true,
            },
            {
                selector: DROPDOWN_CONTAINER_SELECTOR,
                fn: this.compileDropdown,
                doNotCopyAttributes: true,
            },
            {
                selector: `a[type]${NOT_SELF_HANDLED},a[data-type]${NOT_SELF_HANDLED}`,
                fn: this.compileButton,
            },
            {
                selector: `button${NOT_SELF_HANDLED}`,
                fn: this.compileButton,
                doNotCopyAttributes: true,
            },
            { selector: "field", fn: this.compileField },
            { selector: "widget", fn: this.compileWidget },
        ];
        for (const compiler of this.compilers) {
            compiler.builtIn = true;
            compiler.sequence ??= DEFAULT_COMPILER_SEQUENCE;
        }
        this.templates = templates;

        this.owlDirectiveRegexesWhitelist = /** @type {typeof ViewCompiler} */ (
            this.constructor
        ).OWL_DIRECTIVE_WHITELIST.map((d) => new RegExp(d));
        this.baseCompilerCount = this.compilers.length;
        this.setup();
        this._sortCompilers();
    }

    _sortCompilers() {
        this.compilers.sort(
            (a, b) =>
                (a.sequence ?? DEFAULT_COMPILER_SEQUENCE) -
                (b.sequence ?? DEFAULT_COMPILER_SEQUENCE),
        );
    }

    setup() {}

    /**
     * @param {any} invisible
     * @param {Element} compiled
     * @param {Record<string, any>} params
     * @returns {Element | undefined}
     */
    applyInvisible(invisible, compiled, params) {
        const recordExpr = params.recordExpr || "__comp__.props.record";
        let isVisibleExpr = makeIsVisibleExpr(invisible, recordExpr);
        if (isVisibleExpr === "true") {
            return compiled;
        }
        if (isVisibleExpr === "false") {
            return;
        }
        if (compiled.hasAttribute("t-if")) {
            const formerTif = compiled.getAttribute("t-if");
            isVisibleExpr = `( ${formerTif} ) and ${isVisibleExpr}`;
        }
        compiled.setAttribute("t-if", isVisibleExpr);
        return compiled;
    }

    /**
     * @param {string} key
     * @param {Record<string, any>} params
     * @returns {Element}
     */
    compile(key, params = {}) {
        const root = this.templates[key].cloneNode(true);
        this.pairArchDialogs(root);
        const child = this.compileNode(root, params);
        const newRoot = createElement("t", child ? [child] : []);
        newRoot.setAttribute("t-translation", "off");
        return newRoot;
    }

    /**
     * @param {any} node
     * @param {Record<string, any>} params
     * @param {boolean} [evalInvisible]
     * @returns {Element | Text | void}
     */
    compileNode(node, params = {}, evalInvisible = true) {
        if (isComment(node)) {
            return;
        }
        if (isTextNode(node)) {
            return createTextNode(node.nodeValue);
        }

        if (node.hasAttribute("t-translation")) {
            node.removeAttribute("t-translation");
        }
        this.validateNode(node);
        let invisible;
        if (evalInvisible) {
            invisible = getModifier(node, "invisible");
            if (
                !params.compileInvisibleNodes &&
                (invisible === "True" || invisible === "1")
            ) {
                return;
            }
        }

        const winnerIndex = this.compilers.findIndex((cp) => node.matches(cp.selector));
        const compiler = winnerIndex === -1 ? undefined : this.compilers[winnerIndex];
        if (winnerIndex !== -1 && this.compilers.length > this.baseCompilerCount) {
            this._warnShadowedCompilers(node, winnerIndex);
        }
        let compiledNode;
        if (compiler) {
            compiledNode = compiler.fn.call(this, node, params);
            if (!compiler.doNotCopyAttributes && compiledNode) {
                copyAttributes(node, compiledNode);
            }
        } else {
            compiledNode = this.compileGenericNode(node, params);
        }

        if (evalInvisible && compiledNode) {
            compiledNode = this.applyInvisible(invisible, compiledNode, params);
        }
        return compiledNode;
    }

    /**
     * @param {Element} node
     * @param {number} winnerIndex
     */
    _warnShadowedCompilers(node, winnerIndex) {
        for (let i = winnerIndex + 1; i < this.compilers.length; i++) {
            const shadowed = this.compilers[i];
            if (shadowed.builtIn) {
                continue;
            }
            if (!node.matches(shadowed.selector)) {
                continue;
            }
            shadowedCompilerReports.add(
                JSON.stringify({
                    shadowed: shadowed.selector,
                    winner: this.compilers[winnerIndex].selector,
                    compiler: this.constructor.name,
                }),
            );
            if (odoo.debug && !warnedShadowedSelectors.has(shadowed.selector)) {
                warnedShadowedSelectors.add(shadowed.selector);
                console.warn(
                    `[view_compiler] The compiler for "${shadowed.selector}" never ` +
                        `runs: an earlier compiler ("${this.compilers[winnerIndex].selector}") ` +
                        `claims the same node first. Dispatch is first-match-wins and ` +
                        `registered compilers are appended after the built-ins, so a ` +
                        `selector that also matches a built-in target (field, widget, ` +
                        `button, a[type], .modal, dropdown) cannot intercept it. ` +
                        `Give it a lower "sequence" than ${DEFAULT_COMPILER_SEQUENCE} ` +
                        `to dispatch it first.`,
                );
            }
        }
    }

    /**
     * @param {Element} root
     */
    pairArchDialogs(root) {
        for (const trigger of root.querySelectorAll(MODAL_TRIGGER_SELECTOR)) {
            const selector = MODAL_TARGET_ATTRS.map((a) =>
                trigger.getAttribute(a),
            ).find(Boolean);
            if (!selector) {
                continue;
            }
            let modal;
            try {
                modal = root.querySelector(selector);
            } catch {
                continue;
            }
            if (!modal?.classList.contains("modal")) {
                continue;
            }
            const key =
                modal.getAttribute(ARCH_DIALOG_KEY_ATTR) || `archDialog${this.id++}`;
            modal.setAttribute(ARCH_DIALOG_KEY_ATTR, key);
            trigger.setAttribute(ARCH_DIALOG_KEY_ATTR, key);
            for (const dismiss of modal.querySelectorAll(MODAL_DISMISS_SELECTOR)) {
                dismiss.setAttribute(ARCH_DIALOG_KEY_ATTR, key);
            }
        }
    }

    /**
     * @param {Element} el
     * @param {Record<string, any>} params
     * @returns {Element}
     */
    compileModal(el, params) {
        const key = el.getAttribute(ARCH_DIALOG_KEY_ATTR);
        if (!key) {
            return this.compileGenericNode(el, params);
        }
        const openExpr = `${ARCH_DIALOGS_EXPR}['${key}']`;

        const dialog = createElement("Dialog", { "t-if": openExpr });
        dialog.setAttribute("close", `() => ${openExpr} = false`);

        const titleEl = el.querySelector(".modal-title");
        if (titleEl) {
            dialog.setAttribute(
                "title",
                toStringExpression(titleEl.textContent.trim()),
            );
        }
        const footerEl = el.querySelector(".modal-footer");
        if (!footerEl) {
            dialog.setAttribute("footer", "false");
        }

        const bodyEl = el.querySelector(".modal-body");
        for (const child of (bodyEl || el).childNodes) {
            append(dialog, this.compileNode(child, params));
        }
        if (footerEl) {
            const footerSlot = createElement("t", { "t-set-slot": "footer" });
            for (const child of footerEl.childNodes) {
                append(footerSlot, this.compileNode(child, params));
            }
            append(dialog, footerSlot);
        }
        return dialog;
    }

    /**
     * @param {Element} el
     * @param {Record<string, any>} params
     * @returns {Element}
     */
    compileModalControl(el, params) {
        const key = el.getAttribute(ARCH_DIALOG_KEY_ATTR);
        const opens = [SELF_HANDLED_ATTR, "data-bs-toggle"].some(
            (a) => el.getAttribute(a) === "modal",
        );
        for (const attr of [
            SELF_HANDLED_ATTR,
            "data-bs-toggle",
            "data-bs-dismiss",
            "data-modal-dismiss",
            ...MODAL_TARGET_ATTRS,
        ]) {
            el.removeAttribute(attr);
        }
        el.removeAttribute(ARCH_DIALOG_KEY_ATTR);
        const compiled = this.compileNode(el, params, false);
        const element =
            compiled && !isTextNode(compiled)
                ? /** @type {Element} */ (compiled)
                : null;
        if (element && !isComponentNode(element)) {
            element.setAttribute(
                "t-on-click",
                `() => ${ARCH_DIALOGS_EXPR}['${key}'] = ${opens}`,
            );
        }
        return /** @type {Element} */ (element);
    }

    /**
     * @param {Element} el
     * @param {Record<string, any>} params
     * @returns {Element}
     */
    compileDropdown(el, params) {
        const children = [...el.children];
        const toggleEl = children.find((c) => c.matches(DROPDOWN_TOGGLE_SELECTOR));
        const menuEl = children.find((c) => c.classList.contains("dropdown-menu"));
        if (!toggleEl || !menuEl) {
            return this.compileGenericNode(el, params);
        }

        const compiled = createElement(el.nodeName.toLowerCase());
        for (const attr of el.attributes) {
            if (!MODIFIER_ATTRS.includes(attr.name)) {
                compiled.setAttribute(attr.name, attr.value);
            }
        }

        const dropdown = createElement("Dropdown");
        const menuClasses = [...menuEl.classList].filter(
            (c) => c !== "dropdown-menu" && c !== "dropdown-menu-end",
        );
        if (menuClasses.length) {
            dropdown.setAttribute(
                "menuClass",
                toStringExpression(menuClasses.join(" ")),
            );
        }
        if (menuEl.classList.contains("dropdown-menu-end")) {
            dropdown.setAttribute("position", toStringExpression("bottom-end"));
        }

        toggleEl.removeAttribute("data-bs-toggle");
        toggleEl.removeAttribute("aria-expanded");
        toggleEl.setAttribute("data-self-handled", "1");
        append(dropdown, this.compileNode(toggleEl, params));

        const contentSlot = createElement("t");
        contentSlot.setAttribute("t-set-slot", "content");
        for (const child of menuEl.childNodes) {
            append(contentSlot, this.compileNode(child, params));
        }
        append(dropdown, contentSlot);

        for (const child of el.childNodes) {
            if (child === toggleEl) {
                append(compiled, dropdown);
            } else if (child !== menuEl) {
                append(compiled, this.compileNode(child, params));
            }
        }
        return compiled;
    }

    /**
     * @param {Element} el
     * @param {Record<string, any>} params
     * @returns {Element}
     */
    compileButton(el, params) {
        let tag = getTag(el, true);
        const type = el.getAttribute("type");
        if (tag === "a" && type === "url") {
            tag = "button";
        }
        const recordExpr = params.recordExpr || "__comp__.props.record";
        const button = createElement("ViewButton", {
            tag: toStringExpression(tag),
            record: recordExpr,
        });

        assignOwlDirectives(button, el);

        combineAttributes(
            button,
            "className",
            [toStringExpression(el.className), button.className],
            "+` `+",
        );
        el.removeAttribute("class");
        button.removeAttribute("class");

        const clickParams = {};
        const attrs = {};
        const modifiers = {};
        for (const { name, value } of el.attributes) {
            if (BUTTON_CLICK_PARAMS.includes(name)) {
                clickParams[name] = value;
            } else if (name === "disabled") {
                button.setAttribute(
                    "disabled",
                    exprToBoolean(value) ? "true" : "false",
                );
            } else if (BUTTON_MODIFIERS.includes(name)) {
                modifiers[name] = value;
            } else if (BUTTON_STRING_PROPS.includes(name)) {
                button.setAttribute(name, toStringExpression(value));
            } else if (!name.startsWith("t-")) {
                attrs[name] = value;
            }
        }

        button.setAttribute("clickParams", JSON.stringify(clickParams));
        button.setAttribute("attrs", JSON.stringify(attrs));
        button.setAttribute("modifiers", JSON.stringify(modifiers));

        const buttonContent = [];
        for (const child of el.childNodes) {
            const compiled = this.compileNode(child, params);
            if (compiled) {
                buttonContent.push(compiled);
            }
        }
        if (buttonContent.length) {
            const contentSlot = createElement("t");
            contentSlot.setAttribute("t-set-slot", "contents");
            append(button, contentSlot);
            for (const buttonChild of buttonContent) {
                append(contentSlot, buttonChild);
            }
        }
        return button;
    }

    /**
     * @param {Element} el
     * @param {Record<string, any>} params
     * @returns {Element}
     */
    compileField(el, params) {
        const fieldName = el.getAttribute("name");
        const fieldId = el.getAttribute("field_id");

        const field = createElement("Field");
        const recordExpr = params.recordExpr || "__comp__.props.record";
        field.setAttribute("id", toStringExpression(fieldId));
        field.setAttribute("name", toStringExpression(fieldName));
        field.setAttribute("record", recordExpr);
        field.setAttribute(
            "fieldInfo",
            `__comp__.props.archInfo.fieldNodes[${toStringExpression(fieldId)}]`,
        );
        field.setAttribute("readonly", `__comp__.props.readonly`);

        if (el.hasAttribute("widget")) {
            field.setAttribute("type", toStringExpression(el.getAttribute("widget")));
        }

        return field;
    }

    /**
     * @param {Element} el
     * @param {Record<string, any>} params
     * @returns {Element}
     */
    compileGenericNode(el, params) {
        const compiled = createElement(el.nodeName.toLowerCase());
        for (const attr of el.attributes) {
            if (MODIFIER_ATTRS.includes(attr.name)) {
                continue;
            }
            compiled.setAttribute(attr.name, attr.value);
        }
        for (const child of el.childNodes) {
            append(compiled, this.compileNode(child, params));
        }
        if (el.hasAttribute("t-foreach") && !el.hasAttribute("t-key")) {
            compiled.setAttribute("t-key", `${el.getAttribute("t-as")}_index`);
            console.warn(`Missing attribute "t-key" in "t-foreach" statement.`);
        }
        return compiled;
    }

    /**
     * @param {Element} el
     * @returns {Element}
     */
    compileWidget(el) {
        const widgetId = el.getAttribute("widget_id");
        const props = { record: "__comp__.props.record" };
        if (el.hasAttribute("name")) {
            props.name = toStringExpression(el.getAttribute("name"));
        }
        if (el.hasAttribute("class")) {
            props.className = toStringExpression(el.getAttribute("class"));
        }
        props.widgetInfo = `__comp__.props.archInfo.widgetNodes[${toStringExpression(widgetId)}]`;
        const widget = createElement("Widget", props);
        return assignOwlDirectives(widget, el);
    }

    validateNode(node) {
        const regexes = this.owlDirectiveRegexesWhitelist;
        for (const { name } of node.attributes) {
            if (name.startsWith("t-") && !regexes.some((regex) => regex.test(name))) {
                console.warn(`Forbidden directive ${name} used in arch`);
            }
        }
    }
}

let templateCache = new Set();
/**
 * @type {WeakMap<Element, string>}
 */
const archKeyCache = new WeakMap();
/**
 * @type {WeakMap<Function, string>}
 */
const compilerClassKeys = new WeakMap();
let nextCompilerClassId = 1;
function getCompilerClassKey(ViewCompiler) {
    let classKey = compilerClassKeys.get(ViewCompiler);
    if (!classKey) {
        classKey = `${ViewCompiler.name}#${nextCompilerClassId++}`;
        compilerClassKeys.set(ViewCompiler, classKey);
    }
    return classKey;
}
/**
 * @param {Element} template
 * @returns {string}
 */
function getArchKey(template) {
    let archKey = archKeyCache.get(template);
    if (archKey === undefined) {
        const arch = template.outerHTML.replace(/[\n\r]+/g, " ");
        archKey = `${arch.length}-${cyrb53(arch)}`;
        archKeyCache.set(template, archKey);
    }
    return archKey;
}

/**
 * @param {typeof ViewCompiler} ViewCompiler
 * @param {Record<string, Element>} templates
 * @param {Record<string, any>} [params]
 * @returns {Record<string, string>}
 */
export function compileViewTemplates(ViewCompiler, templates, params) {
    /** @type {Record<string, string>} */
    const compiledTemplates = {};
    let compiler;
    const paramsKey = params
        ? JSON.stringify(Object.entries(params).sort(([a], [b]) => a.localeCompare(b)))
        : "";
    const names = Object.keys(templates);
    const setKey = cyrb53(
        names
            .map((name) => `${name}:${getArchKey(templates[name])}`)
            .sort()
            .join("|"),
    );
    for (const tname of names) {
        const archKey = getArchKey(templates[tname]);
        const key = `${getCompilerClassKey(ViewCompiler)}/${paramsKey}/${setKey}/${archKey}`;
        if (!templateCache.has(key)) {
            compiler = compiler || new ViewCompiler(templates);
            const compiledOuterHTML = compiler.compile(tname, params).outerHTML;
            /** @type {any} */ (App).registerTemplate(key, compiledOuterHTML);
            templateCache.add(key);
        }
        compiledTemplates[tname] = key;
    }
    return compiledTemplates;
}

export function resetViewCompilerCache() {
    templateCache = new Set();
    shadowedCompilerReports.clear();
    warnedShadowedSelectors.clear();
}
