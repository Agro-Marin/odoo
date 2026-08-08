// @ts-check
/** @odoo-module native */

/** @module @web/views/view_compiler */

/**
 * @typedef Compiler
 * @property {string} selector
 * @property {(el: Element, params: Record<string, any>) => Element} fn
 * @property {string} [class]
 * @property {boolean} [doNotCopyAttributes]
 * @property {number} [sequence] dispatch order, lowest first; defaults to
 *   `DEFAULT_COMPILER_SEQUENCE`. Below it to intercept a node the built-ins also
 *   match, above it to run only where they do not.
 * @property {boolean} [builtIn] set by the constructor on the base compilers;
 *   shadow reporting is about extensions being suppressed, so it skips these.
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
import { BUTTON_CLICK_PARAMS } from "./view_buttons.js";
import { toStringExpression } from "./view_utils.js";
const BUTTON_STRING_PROPS = ["string", "size", "title", "icon", "id"];
const INTERP_REGEXP = /(\{\{|#\{)(.*?)(\}{1,2})/g;

/** Modifiers consumed by the compiler itself; never copied onto the output. */
const MODIFIER_ATTRS = ["column_invisible", "invisible", "readonly", "required"];

/**
 * Arch tags that own their compilation: each has its own entry in
 * `ViewCompiler.compilers` and turns into a component, not into markup. A Bootstrap
 * positioning class on one of them is styling for the wrapper that component renders
 * — never a dropdown container, whose recognised shape is a *parent* directly holding
 * a toggle and a menu, something these tags never have as children.
 *
 * They are excluded from the dropdown selector because dispatch is first-match-wins
 * and the dropdown entry precedes theirs. Without this, `<field class="btn-group"/>`,
 * `<widget class="btn-group"/>` and `<button type="object" class="btn-group"/>` were
 * claimed by `compileDropdown`, found no toggle/menu pair, and fell through to
 * `compileGenericNode` — emitting the raw arch tag into the DOM as an inert element.
 * The field never rendered, the widget never instantiated and the button did nothing
 * when clicked, all silently, decided by a *class name*.
 * Guarded by `stock/static/tests/operations_form_arch.test.js`.
 */
const NOT_SELF_COMPILING_TAG =
    ":not(field):not(widget):not(button):not(a[type]):not(a[data-type])";

/**
 * Elements Bootstrap accepts as a dropdown's positioning parent. A construct is
 * only recognised when one of these directly contains both the toggle and the
 * menu, which is also the shape Bootstrap itself documents. A bare
 * toggle/menu pair with no such parent is left alone.
 */
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

/**
 * Marks the two halves of a modal construct — the control that opens it and the
 * `.modal` itself — with a shared key, so each can compile to the same entry of
 * the renderer's `archDialogs` state. Bootstrap pairs them with a CSS selector
 * in `data-bs-target`, which only resolves at runtime; the pairing has to be
 * resolved once, up front, while the whole arch tree is still in hand.
 */
const ARCH_DIALOG_KEY_ATTR = "data-arch-dialog";
const MODAL_TRIGGER_SELECTOR = selfHandledSelector("modal")
    .split(",")
    .flatMap((control) => MODAL_TARGET_ATTRS.map((attr) => `${control}[${attr}]`))
    .join(",");
const MODAL_DISMISS_SELECTOR = '[data-modal-dismiss],[data-bs-dismiss="modal"]';
const ARCH_DIALOGS_EXPR = "__comp__.archDialogs";

/**
 * The dispatch priority every built-in carries, and the default for anything
 * that declares none. Mid-scale on purpose, so an extension has room on both
 * sides without renumbering the built-ins.
 */
export const DEFAULT_COMPILER_SEQUENCE = 50;

/**
 * @param {string} str
 * @returns {string}
 */
export function toInterpolatedStringExpression(str) {
    const matches = str.matchAll(INTERP_REGEXP);
    const parts = [];
    let searchString = str;
    for (const [match, head, expr] of matches) {
        const index = searchString.indexOf(head);
        const left = searchString.slice(0, index);
        if (left) {
            parts.push(toStringExpression(left));
        }
        parts.push(`(${expr})`);
        searchString = searchString.slice(index + match.length);
    }
    parts.push(toStringExpression(searchString));
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
 * Selectors already reported by `_warnShadowedCompilers`, module-scoped so the
 * warning fires once per shadowed selector across every compile rather than on
 * every node.
 * @type {Set<string>}
 */
const warnedShadowedSelectors = new Set();

/**
 * Every shadowing seen since the last reset, as
 * `{shadowed, winner, compiler}` — the extension's selector, the selector that
 * claimed the node first, and the compiler class it happened in.
 *
 * Recorded unconditionally; only the `console.warn` is debug-gated. Detection
 * used to be gated too, which put the one signal that an extension never runs
 * behind the flag least likely to be set where it matters. A silently
 * non-rendering compiler in production is exactly the case worth catching, and a
 * record nothing prints costs a Set insertion on a path that runs once per arch
 * (compiled templates are cached by arch hash).
 *
 * @type {Set<string>}
 */
const shadowedCompilerReports = new Set();

/** Every shadowing recorded so far. Read by tests; see `resetViewCompilerCache`. */
export function getShadowedCompilerReports() {
    return [...shadowedCompilerReports].map((entry) => JSON.parse(entry));
}

export class ViewCompiler {
    constructor(templates) {
        /** @type {number} */
        this.id = 1;
        /** @type {Compiler[]} */
        this.compilers = [
            {
                // The modal itself carries the key too, hence the exclusion.
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

        this.owlDirectiveRegexesWhitelist = /** @type {any} */ (
            this.constructor
        ).OWL_DIRECTIVE_WHITELIST.map((/** @type {string} */ d) => new RegExp(d));
        // Everything a subclass appends in `setup()` (notably the registry-
        // contributed `form_compilers`) lands after this point; dispatch is
        // first-match-wins over `this.compilers` in order, so those late entries
        // can be silently shadowed by a built-in. Record the boundary to warn.
        this.baseCompilerCount = this.compilers.length;
        this.setup();
        this._sortCompilers();
    }

    /**
     * Order dispatch by declared `sequence`, lowest first.
     *
     * Dispatch is first-match-wins, and before this the order was whatever
     * `setup()` happened to do to the array. A subclass needing to intercept a
     * node the built-ins also match had one move — `unshift` — and one needing
     * to run after them had another — `push` — with the array position standing
     * in for a priority nobody wrote down. `project_task_kanban_compiler` uses
     * `unshift` for exactly that reason.
     *
     * The sort is **stable** and every built-in carries
     * `DEFAULT_COMPILER_SEQUENCE`, so an entry that declares no sequence keeps
     * the position `push`/`unshift` gave it: both existing idioms mean what they
     * have always meant, and `sequence` is how a new one says so out loud.
     */
    _sortCompilers() {
        // Array.prototype.sort is required to be stable (ES2019), which is what
        // makes the no-sequence case a no-op rather than a reshuffle.
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
        // Only worth walking when a subclass actually contributed something; a
        // stock compiler can shadow nothing but its own built-ins, which is the
        // documented dispatch order rather than a defect.
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
     * A registered (subclass-appended) compiler that also matches a node an
     * earlier compiler already claimed never runs -- first-match-wins reaches
     * the earlier one first, and registry entries are appended after the
     * built-ins, so a selector that also matches a built-in target (field,
     * widget, button, a[type], .modal, dropdown) cannot intercept it. The
     * registration validates and is then silently never dispatched.
     *
     * Every occurrence is recorded in `shadowedCompilerReports`, whatever the
     * debug flag; debug additionally warns once per shadowed selector so an
     * addon author sees the dead compiler. Built-in-vs-built-in overlap is
     * deliberate ordering, not a bug, so entries carrying `builtIn` are skipped.
     *
     * A shadowed compiler is now avoidable rather than merely detectable: give
     * it a `sequence` below `DEFAULT_COMPILER_SEQUENCE` and it dispatches first.
     *
     * @param {Element} node
     * @param {number} winnerIndex
     */
    _warnShadowedCompilers(node, winnerIndex) {
        for (let i = winnerIndex + 1; i < this.compilers.length; i++) {
            const shadowed = this.compilers[i];
            // Index is no longer the test: `_sortCompilers` reorders by
            // sequence, so `baseCompilerCount` stopped identifying which entries
            // are built-in the moment an extension declared a sequence below
            // them. The flag survives the sort.
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
     * Resolve every `data-bs-target` selector to the `.modal` it names and stamp
     * both ends with a shared key. Run once per template, before compilation,
     * because a trigger and its modal sit in different branches of the arch and
     * are compiled independently.
     *
     * A modal nobody opens, or a trigger pointing at nothing, is left unpaired
     * and so compiles as ordinary markup.
     *
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
                // `data-bs-target` is author-written and need not be valid CSS.
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
     * Compile a `.modal` written in arch into the web client's own `Dialog`.
     *
     * Bootstrap's modal is a block of markup that is present but hidden until
     * its data-api shows it; `Dialog` is mounted into the overlay only while
     * open. The open flag therefore has to live somewhere, and the renderer
     * owns it: `archDialogs` is keyed by the pairing above, so the trigger and
     * every dismiss control inside the modal address the same entry.
     *
     * @param {Element} el
     * @param {Record<string, any>} params
     * @returns {Element}
     */
    compileModal(el, params) {
        const key = el.getAttribute(ARCH_DIALOG_KEY_ATTR);
        if (!key) {
            // No control in this arch opens it, so there is nothing to drive.
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
     * Compile a control that opens or closes a paired modal.
     *
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
        // The control keeps whatever else it declares, so a dismissing
        // `<a type="action">` still compiles to its action button.
        const compiled = this.compileNode(el, params, false);
        // `compileNode` also answers with text nodes and with nothing at all;
        // only an element can carry the handler.
        const element =
            compiled && !isTextNode(compiled)
                ? /** @type {Element} */ (compiled)
                : null;
        // A control that compiled to a component takes no DOM handler: OWL
        // does not bind `t-on-*` on a component node, and emitting one would
        // produce a template that fails to compile. Such a control runs its
        // own action and leaves the dialog to whatever that action triggers.
        if (element && !isComponentNode(element)) {
            element.setAttribute(
                "t-on-click",
                `() => ${ARCH_DIALOGS_EXPR}['${key}'] = ${opens}`,
            );
        }
        return /** @type {Element} */ (element);
    }

    /**
     * Compile a Bootstrap dropdown written in arch into an OWL `Dropdown`.
     *
     * Arch — including arch stored in the database, which no source grep can
     * reach — has always spelled a dropdown as a positioning container holding
     * a `data-bs-toggle="dropdown"` control and a sibling `.dropdown-menu`.
     * Recognising that shape here is what lets those views keep working once
     * Bootstrap's JS is gone, rather than each one having to be rewritten.
     *
     * The container itself is kept and compiled as an ordinary element: its
     * classes and modifiers belong to the surrounding layout, and `Dropdown`
     * takes no class of its own. Only the toggle/menu pair inside it is
     * replaced.
     *
     * @param {Element} el
     * @param {Record<string, any>} params
     * @returns {Element}
     */
    compileDropdown(el, params) {
        const children = [...el.children];
        const toggleEl = children.find((c) => c.matches(DROPDOWN_TOGGLE_SELECTOR));
        const menuEl = children.find((c) => c.classList.contains("dropdown-menu"));
        if (!toggleEl || !menuEl) {
            // A positioning class used for layout only, with no dropdown in it.
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
            // Bootstrap aligns the menu with a class; `Dropdown` positions it.
            dropdown.setAttribute("position", toStringExpression("bottom-end"));
        }

        // Swapped rather than dropped: the toggle must stop being a Bootstrap
        // control (or the data-api would open a second menu once both are on
        // the page) while still being excluded from `compileButton`, which
        // would otherwise read its `type="button"` as an Odoo action type.
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
        for (const { name, value } of el.attributes) {
            if (BUTTON_CLICK_PARAMS.includes(name)) {
                clickParams[name] = value;
            } else if (name === "disabled") {
                button.setAttribute(
                    "disabled",
                    exprToBoolean(value) ? "true" : "false",
                );
            } else if (BUTTON_STRING_PROPS.includes(name)) {
                button.setAttribute(name, toStringExpression(value));
            } else if (!name.startsWith("t-")) {
                attrs[name] = value;
            }
        }

        button.setAttribute("clickParams", JSON.stringify(clickParams));
        button.setAttribute("attrs", JSON.stringify(attrs));

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
        const attributes = Object.values(node.attributes).map((attr) => attr.name);
        const regexes = this.owlDirectiveRegexesWhitelist;
        for (const attr of attributes) {
            if (attr.startsWith("t-") && !regexes.some((regex) => regex.test(attr))) {
                console.warn(`Forbidden directive ${attr} used in arch`);
            }
        }
    }
}
ViewCompiler.OWL_DIRECTIVE_WHITELIST = [];

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
/**
 * The key is the class **object**, so it survives `patch()`: patching a
 * compiler's prototype mutates it in place and leaves the class identity — and
 * therefore this key — unchanged. Anything already compiled under it stays
 * cached and the patch does not reach it.
 *
 * That is latent rather than live today, because patches apply at module
 * evaluation, before any view renders. It becomes reachable the moment a
 * **lazily loaded bundle** patches a compiler after a view of that class has
 * already rendered — worth knowing before the next lazy-bundle split, since the
 * symptom would be a patch that silently does nothing for one arch and works
 * for the next.
 */
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
export function useViewCompiler(ViewCompiler, templates, params) {
    /** @type {Record<string, string>} */
    const compiledTemplates = {};
    let compiler;
    const paramsKey = params
        ? JSON.stringify(Object.entries(params).sort(([a], [b]) => a.localeCompare(b)))
        : "";
    const names = Object.keys(templates);
    // A compiler is handed the whole template map and may read siblings while
    // compiling one of them — `KanbanCompiler.compileTCall` emits a different
    // `t-call` depending on whether the called name is a sibling. The same arch
    // therefore compiles two ways, so the set is part of the cache identity;
    // keying on one member's arch alone lets the two share a slot and makes
    // whichever view compiled first decide how the other renders.
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
    // Both shadow-tracking sets are module state with the same lifetime as the
    // cache: a suite that compiled a deliberately-shadowed compiler would
    // otherwise leak the record into the next one, and the once-per-selector
    // warning would stay suppressed for the rest of the run.
    shadowedCompilerReports.clear();
    warnedShadowedSelectors.clear();
}
