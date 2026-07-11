// @ts-check
/** @odoo-module native */

/** @module @web/public/colibri - Mini-framework runtime that manages Interaction lifecycles, dynamic content, and event bindings for public pages */

/** @import { Interaction } from "@web/public/interaction" */

import { Component, markup } from "@odoo/owl";

// Markup class is not exported by @odoo/owl; derive it once from a markup()
// instance.  The pre-ESM code looked it up lazily via `owl.markup` (global
// `owl` object), which fails under strict-mode ESM where there is no global.
const Markup = markup("").constructor;

export const INITIAL_VALUE = Symbol("initial value");
// Return this from event handlers to skip updateContent.
export const SKIP_IMPLICIT_UPDATE = Symbol();

export class Colibri {
    /**
     * @param {any} core the InteractionService that owns this Colibri instance
     * @param {typeof Interaction} I the Interaction class to instantiate
     * @param {HTMLElement} el the root element for the interaction
     */
    constructor(core, I, el) {
        this.el = el;
        this.isReady = false;
        this.hasStarted = false;
        this.isUpdating = false;
        this.isDestroyed = false;
        this.dynamicAttrs = [];
        this.tOuts = [];
        this.cleanups = [];
        // Index into `cleanups`, keyed by node, so `refreshNodes` can splice
        // out entries for nodes that leave the DOM (avoids unbounded growth /
        // detached-node retention under dynamic-content churn).
        /** @type {Map<Node, Array<() => void>>} */
        this.nodeCleanups = new Map();
        this.listeners = new Map();
        this.dynamicNodes = new Map();
        this.core = core;
        this.interaction = new I(el, core.env, this);
        this.setupInteraction();
    }

    /** @returns {void} */
    setupInteraction() {
        this.interaction.setup();
    }

    /** @returns {void} */
    destroyInteraction() {
        for (const cleanup of this.cleanups.reverse()) {
            cleanup();
        }
        this.cleanups = [];
        this.nodeCleanups.clear();
        this.interaction.destroy();
    }

    /**
     * @param {Record<string, Record<string, any>> | undefined} content dynamicContent descriptor
     * @returns {void}
     */
    startInteraction(content) {
        if (content) {
            this.processContent(content);
            this.updateContent();
        }
        this.interaction.start();
        this.hasStarted = true;
    }

    /**
     * Runs willStart() and then starts the interaction.
     *
     * @returns {Promise<void>}
     */
    async start() {
        await this.interaction.willStart();
        if (this.isDestroyed) {
            return;
        }
        this.isReady = true;
        const content = this.interaction.dynamicContent;
        this.startInteraction(content);
    }

    /**
     * Attaches an event listener to nodes, with optional modifier suffixes
     * (.prevent, .stop, .once, .capture, .noUpdate, .withTarget).
     *
     * @param {Iterable<EventTarget>} nodes
     * @param {string} event event name, optionally with dot-suffixed modifiers
     * @param {Function} fn
     * @param {AddEventListenerOptions} [options]
     * @returns {[string, EventListener, AddEventListenerOptions | undefined]}
     */
    addListener(nodes, event, fn, options) {
        if (typeof fn !== "function") {
            throw new Error(`Invalid listener for event '${event}' (not a function)`);
        }
        if (!this.isReady) {
            throw new Error(
                "this.addListener can only be called after the interaction is started. Maybe move the call in the start method.",
            );
        }
        const re =
            /^(?<event>.*)\.(?<suffix>prevent|stop|capture|once|noUpdate|withTarget)$/;
        let groups = re.exec(event)?.groups;
        while (groups) {
            fn = {
                prevent:
                    (f) =>
                    (ev, ...args) => {
                        ev.preventDefault();
                        return f.call(this.interaction, ev, ...args);
                    },
                stop:
                    (f) =>
                    (ev, ...args) => {
                        ev.stopPropagation();
                        return f.call(this.interaction, ev, ...args);
                    },
                capture: (f) => {
                    options ||= {};
                    options.capture = true;
                    return f;
                },
                once: (f) => {
                    options ||= {};
                    options.once = true;
                    return f;
                },
                noUpdate:
                    (f) =>
                    (...args) => {
                        f.call(this.interaction, ...args);
                        return SKIP_IMPLICIT_UPDATE;
                    },
                withTarget:
                    (f) =>
                    (ev, ...args) => {
                        const currentTarget = ev.currentTarget;
                        return f.call(this.interaction, ev, currentTarget, ...args);
                    },
            }[groups.suffix](fn);
            event = groups.event;
            groups = re.exec(event)?.groups;
        }
        const fnAny = /** @type {any} */ (fn);
        const handler = fnAny.isHandler
            ? fn
            : async (...args) => {
                  if (
                      SKIP_IMPLICIT_UPDATE !==
                      (await fn.call(this.interaction, ...args))
                  ) {
                      if (!this.isDestroyed) {
                          this.updateContent();
                      }
                  }
              };
        /** @type {any} */ (handler).isHandler = true;
        const eventListener = /** @type {EventListener} */ (handler);
        for (const node of nodes) {
            node.addEventListener(event, eventListener, options);
            const remover = () =>
                node.removeEventListener(event, eventListener, options);
            // Keep the remover in the single ordered `cleanups` list AND index
            // it by node, so `refreshNodes` can splice it back out when the
            // node leaves the DOM.
            this.cleanups.push(remover);
            let removers = this.nodeCleanups.get(node);
            if (!removers) {
                removers = [];
                this.nodeCleanups.set(node, removers);
            }
            removers.push(remover);
        }
        return [event, eventListener, options];
    }

    /** @returns {void} */
    refreshNodes() {
        for (const sel of this.dynamicNodes.keys()) {
            const nodes = this.getNodes(sel);
            if (this.listeners.has(sel)) {
                const newNodes = new Set(nodes);
                const oldNodes = this.dynamicNodes.get(sel);
                const events = this.listeners.get(sel);
                const toRemove = new Set();
                for (const node of oldNodes) {
                    if (newNodes.has(node)) {
                        newNodes.delete(node);
                    } else {
                        toRemove.add(node);
                    }
                }
                for (const event of Object.keys(events)) {
                    const [handler, options] = events[event];
                    for (const node of toRemove) {
                        node.removeEventListener(event, handler, options);
                    }
                    if (newNodes.size) {
                        this.addListener(newNodes, event, handler, options);
                    }
                }
                // The departed nodes' listeners were just removed above; splice
                // their (now no-op) removers out of `cleanups` and drop the
                // index entries, so neither grows unbounded nor retains the
                // detached nodes.
                for (const node of toRemove) {
                    const removers = this.nodeCleanups.get(node);
                    if (removers) {
                        for (const remover of removers) {
                            const i = this.cleanups.indexOf(remover);
                            if (i !== -1) {
                                this.cleanups.splice(i, 1);
                            }
                        }
                        this.nodeCleanups.delete(node);
                    }
                }
            }
            this.dynamicNodes.set(sel, nodes);
        }
    }

    /**
     * @param {string} sel
     * @param {string} event
     * @param {EventListener} handler
     * @param {AddEventListenerOptions | undefined} options
     * @returns {void}
     */
    mapSelectorToListeners(sel, event, handler, options) {
        if (this.listeners.has(sel)) {
            this.listeners.get(sel)[event] = [handler, options];
        } else {
            this.listeners.set(sel, { [event]: [handler, options] });
        }
    }

    /**
     * Mounts an OWL component inside `node` and registers cleanup.
     *
     * @param {HTMLElement} node
     * @param {import("@odoo/owl").ComponentConstructor} C
     * @param {Record<string, any>} [props]
     * @param {InsertPosition} [position]
     * @returns {() => void} cleanup function
     */
    mountComponent(node, C, props, position = "beforeend") {
        const root = this.core.prepareRoot(node, C, props, position);
        root.mount();
        this.cleanups.push(() => root.destroy());
        return root.destroy;
    }

    /**
     * Applies a t-out directive: sets textContent or innerHTML for Markup values.
     *
     * @param {HTMLElement} el
     * @param {any} value
     * @param {any} [initialValue]
     * @param {boolean} [restoring] true when restoring initial content during
     *  destroy(): interactions in the replaced content are stopped but not
     *  rescanned for restart, since a global stopInteractions() must not
     *  resurrect them mid-stop.
     * @returns {void}
     */
    applyTOut(el, value, initialValue, restoring = false) {
        if (value === INITIAL_VALUE) {
            value = initialValue;
        }
        if (value instanceof Markup) {
            let nodes = el === this.interaction.el ? el.children : [el];
            for (const node of nodes) {
                this.core.env.services["public.interactions"].stopInteractions(node);
            }
            // Markup wraps a string; .toString() returns the underlying HTML.
            el.innerHTML = value.toString();
            if (!restoring) {
                if (el === this.interaction.el) {
                    nodes = el.children;
                }
                for (const node of nodes) {
                    this.core.env.services["public.interactions"].startInteractions(
                        node,
                    );
                }
                this.refreshNodes();
            }
        } else {
            el.textContent = value;
        }
    }

    /**
     * Applies a t-att directive: sets class, style, or a generic attribute.
     * For class/style, `value` is a plain object; for other attrs, a scalar.
     *
     * @param {HTMLElement} el
     * @param {string} attr attribute name ("class", "style", or any HTML attribute)
     * @param {any} value new value (object for class/style, scalar otherwise)
     * @param {any} [initialValue] original value captured before first update
     * @returns {void}
     */
    applyAttr(el, attr, value, initialValue) {
        if (attr === "class") {
            if (typeof value !== "object") {
                throw new Error("t-att-class directive expects an object");
            }
            for (const cl of Object.keys(value)) {
                const toApply = value[cl];
                for (const c of cl.trim().split(" ")) {
                    // initialValue is keyed per individual class (multi-class
                    // keys are split at capture time), so each class of an
                    // "a b" key restores to its own initial presence.
                    const apply = toApply === INITIAL_VALUE ? initialValue[c] : toApply;
                    el.classList.toggle(c, apply || false);
                }
            }
        } else if (attr === "style") {
            if (typeof value !== "object") {
                throw new Error("t-att-style directive expects an object");
            }
            for (const prop of Object.keys(value)) {
                let style = value[prop];
                if (style === INITIAL_VALUE) {
                    style = initialValue[prop];
                }
                if (style === undefined) {
                    el.style.removeProperty(prop);
                } else {
                    style = String(style);
                    if (style.endsWith(" !important")) {
                        el.style.setProperty(prop, style.slice(0, -11), "important");
                    } else {
                        el.style.setProperty(prop, style);
                    }
                }
            }
        } else {
            if (value === INITIAL_VALUE) {
                value = initialValue;
            }
            if ([false, undefined, null].includes(value)) {
                el.removeAttribute(attr);
            } else {
                if (value === true) {
                    value = attr;
                }
                el.setAttribute(attr, value);
            }
        }
    }

    /**
     * Returns the DOM nodes for a selector, using dynamicSelectors overrides if present.
     *
     * @param {string} sel CSS selector or dynamic selector key
     * @returns {Iterable<HTMLElement>}
     */
    getNodes(sel) {
        const selectors = this.interaction.dynamicSelectors;
        if (sel in selectors) {
            const elems = selectors[sel]();
            if (elems) {
                if (elems.nodeName && ["FORM", "SELECT"].includes(elems.nodeName)) {
                    return [elems];
                }
                return elems[Symbol.iterator] ? elems : [elems];
            } else {
                return [];
            }
        }
        return this.interaction.el.querySelectorAll(sel);
    }

    /**
     * Parses a dynamicContent descriptor: registers event listeners, dynamic
     * attributes, t-out bindings, and t-component mounts.
     *
     * @param {Record<string, Record<string, any>>} content
     * @returns {void}
     */
    processContent(content) {
        for (const sel of Object.keys(content)) {
            if (sel.startsWith("t-")) {
                throw new Error(
                    `Selector missing for key ${sel} in dynamicContent (interaction '${this.interaction.constructor.name}').`,
                );
            }
            let nodes;
            if (this.dynamicNodes.has(sel)) {
                nodes = this.dynamicNodes.get(sel);
            } else {
                nodes = this.getNodes(sel);
                this.dynamicNodes.set(sel, nodes);
            }
            const descr = content[sel];
            for (const directive of Object.keys(descr)) {
                const value = descr[directive];
                if (directive.startsWith("t-on-")) {
                    const ev = directive.slice(5);
                    const [event, handler, options] = this.addListener(
                        nodes,
                        ev,
                        value,
                    );
                    this.mapSelectorToListeners(sel, event, handler, options);
                } else if (directive.startsWith("t-att-")) {
                    const attr = directive.slice(6);
                    this.dynamicAttrs.push({
                        sel,
                        attr,
                        definition: value,
                        initialValues: null,
                    });
                } else if (directive === "t-out") {
                    this.tOuts.push({
                        sel,
                        definition: value,
                        initialValue: null,
                    });
                } else if (directive === "t-component") {
                    if (Object.prototype.isPrototypeOf.call(Component, value)) {
                        for (const node of nodes) {
                            this.mountComponent(node, value);
                        }
                    } else {
                        for (const node of nodes) {
                            const [C, props, pos] =
                                /** @type {[import("@odoo/owl").ComponentConstructor, Record<string, any>?, InsertPosition?]} */ (
                                    value(node)
                                );
                            this.mountComponent(node, C, props, pos);
                        }
                    }
                } else {
                    const suffix = directive.startsWith("t-")
                        ? ""
                        : " (should start with t-)";
                    throw new Error(`Invalid directive: '${directive}'${suffix}`);
                }
            }
        }
    }

    /**
     * Re-evaluates all dynamic attributes and t-out definitions and applies
     * them to the DOM. Called after events or explicit state changes.
     *
     * @returns {void}
     */
    updateContent() {
        if (this.isDestroyed || !this.isReady) {
            throw new Error(
                "Cannot update content of an interaction that is not ready or is destroyed",
            );
        }
        if (this.isUpdating) {
            throw new Error(
                "Updatecontent should not be called while interaction is updating",
            );
        }
        this.isUpdating = true;
        const errors = [];
        try {
            this.applyContent(errors);
        } finally {
            this.isUpdating = false;
        }
        if (errors.length) {
            const name = this.interaction.constructor.name;
            const toError = ({ error, description }) =>
                new Error(
                    `An error occured while updating ${description} (in interaction '${name}')`,
                    { cause: error },
                );
            if (errors.length === 1) {
                throw toError(errors[0]);
            }
            throw new AggregateError(
                errors.map(toError),
                `Some errors occured while updating content (in interaction '${name}')`,
            );
        }
    }

    /**
     * Applies dynamic attributes and t-out definitions to the DOM, collecting
     * errors instead of aborting so that a single failing definition does not
     * prevent the rest of the content from being updated.
     *
     * @param {Array<{ error: Error, description: string }>} errors
     * @returns {void}
     */
    applyContent(errors) {
        if (this.hasStarted) {
            try {
                this.refreshNodes();
            } catch (error) {
                errors.push({ error, description: "dynamic nodes" });
            }
        }
        const interaction = this.interaction;
        for (const dynamicAttr of this.dynamicAttrs) {
            const { sel, attr, definition } = dynamicAttr;
            let { initialValues } = dynamicAttr;
            const nodes = this.dynamicNodes.get(sel) || [];
            if (!initialValues && nodes.length) {
                initialValues = new Map();
                dynamicAttr.initialValues = initialValues;
            }
            for (const node of nodes) {
                try {
                    const value = definition.call(interaction, node);
                    if (!initialValues || !initialValues.has(node)) {
                        let attrValue;
                        switch (attr) {
                            case "class":
                                // Capture per individual class: a multi-class
                                // key ("a b") can never satisfy classList
                                // .contains and each class may differ in
                                // initial presence.
                                attrValue = {};
                                for (const classNames of Object.keys(value)) {
                                    for (const c of classNames.trim().split(" ")) {
                                        attrValue[c] = node.classList.contains(c);
                                    }
                                }
                                break;
                            case "style":
                                attrValue = {};
                                for (const property of Object.keys(value)) {
                                    const propertyValue =
                                        node.style.getPropertyValue(property);
                                    const priority =
                                        node.style.getPropertyPriority(property);
                                    attrValue[property] = propertyValue
                                        ? propertyValue +
                                          (priority ? ` !${priority}` : "")
                                        : undefined;
                                }
                                break;
                            default:
                                attrValue = node.getAttribute(attr);
                        }
                        initialValues.set(node, attrValue);
                    }
                    this.applyAttr(
                        node,
                        attr,
                        value,
                        dynamicAttr.initialValues.get(node),
                    );
                } catch (error) {
                    errors.push({
                        error,
                        description: `dynamic attribute '${attr}'`,
                    });
                }
            }
        }
        for (const tOut of this.tOuts) {
            const { sel, definition } = tOut;
            let { initialValue } = tOut;
            const nodes = this.dynamicNodes.get(sel) || [];
            if (!initialValue && nodes.length) {
                initialValue = new Map();
                tOut.initialValue = initialValue;
            }
            for (const node of nodes) {
                try {
                    if (!initialValue || !initialValue.has(node)) {
                        const value = node.children.length
                            ? markup(node.innerHTML)
                            : node.textContent;
                        initialValue.set(node, value);
                    }
                    this.applyTOut(
                        node,
                        definition.call(interaction, node),
                        tOut.initialValue.get(node),
                    );
                } catch (error) {
                    errors.push({
                        error,
                        description: `'t-out' content (selector '${sel}')`,
                    });
                }
            }
        }
    }

    /**
     * Restores all dynamic attributes and t-out values to their initial state,
     * removes event listeners, destroys the interaction, and marks this
     * Colibri as destroyed.
     *
     * @returns {void}
     */
    destroy() {
        const errors = [];
        try {
            // restore t-att to their initial values
            for (const dynAttrs of this.dynamicAttrs) {
                const { sel, attr, initialValues } = dynAttrs;
                if (!initialValues) {
                    continue;
                }
                for (const node of this.dynamicNodes.get(sel) || []) {
                    if (initialValues.has(node)) {
                        try {
                            this.applyAttr(node, attr, initialValues.get(node));
                        } catch (error) {
                            errors.push(error);
                        }
                    }
                }
            }

            // restore t-out to their initial values (`restoring`: do not
            // start interactions found in the restored content)
            for (const tOut of this.tOuts) {
                const { sel, initialValue } = tOut;
                if (!initialValue) {
                    continue;
                }
                for (const node of this.dynamicNodes.get(sel) || []) {
                    if (initialValue.has(node)) {
                        try {
                            this.applyTOut(node, initialValue.get(node), null, true);
                        } catch (error) {
                            errors.push(error);
                        }
                    }
                }
            }
        } finally {
            // even if the restore phase crashed, listeners and cleanups must
            // be removed: the service drops this Colibri no matter what.
            this.listeners.clear();
            this.dynamicNodes.clear();
            try {
                this.destroyInteraction();
            } finally {
                this.core = null;
                this.isDestroyed = true;
                this.isReady = false;
            }
        }
        if (errors.length) {
            if (errors.length === 1) {
                throw errors[0];
            }
            throw new AggregateError(
                errors,
                `Some errors occured while restoring content (in interaction '${this.interaction.constructor.name}')`,
            );
        }
    }

    /**
     * Patchable hook for protecting synchronous code that runs after an
     * await (e.g. after `await waitFor(...)`).
     *
     * @param {Interaction} interaction
     * @param {string} name method name (used by patches for identification)
     * @param {Function} fn the synchronous function to protect
     * @returns {Function}
     */
    protectSyncAfterAsync(interaction, name, fn) {
        return fn.bind(interaction);
    }
}
