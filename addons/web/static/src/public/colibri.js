// @ts-check
/** @odoo-module native */

/** @import { Interaction } from "@web/public/interaction" */

import { Component, markup } from "@odoo/owl";

const Markup = markup("").constructor;

export const INITIAL_VALUE = Symbol("initial value");
export const SKIP_IMPLICIT_UPDATE = Symbol();

const EVENT_MODIFIER_RE =
    /^(?<event>.*)\.(?<suffix>prevent|stop|capture|once|noUpdate|withTarget|keepInHistory)$/;

/**
 * @type {Record<string, (fn: Function, colibri: Colibri) => (...args: any[]) => any>}
 */
const EVENT_MODIFIERS = {
    prevent:
        (fn, colibri) =>
        (ev, ...args) => {
            ev.preventDefault();
            return fn.call(colibri.interaction, ev, ...args);
        },
    stop:
        (fn, colibri) =>
        (ev, ...args) => {
            ev.stopPropagation();
            return fn.call(colibri.interaction, ev, ...args);
        },
    noUpdate:
        (fn, colibri) =>
        async (...args) => {
            await fn.call(colibri.interaction, ...args);
            return SKIP_IMPLICIT_UPDATE;
        },
    withTarget:
        (fn, colibri) =>
        (ev, ...args) =>
            fn.call(colibri.interaction, ev, ev.currentTarget, ...args),
};

/**
 * @param {any} target
 * @returns {Iterable<any>}
 */
export function toEventTargets(target) {
    if (target === null || target === undefined) {
        return [];
    }
    if (typeof target.nodeType === "number" || !target[Symbol.iterator]) {
        return [target];
    }
    return target;
}

/**
 * @param {string} names
 * @returns {string[]}
 */
function splitClassNames(names) {
    return names.split(/\s+/).filter(Boolean);
}

/**
 * @param {HTMLElement} el
 * @param {any} value
 * @returns {boolean}
 */
function isSameTextContent(el, value) {
    const text = value === null || value === undefined ? "" : String(value);
    const child = el.firstChild;
    if (!child) {
        return text === "";
    }
    return (
        child === el.lastChild &&
        child.nodeType === Node.TEXT_NODE &&
        /** @type {Text} */ (child).data === text
    );
}

/**
 * @param {any} a
 * @param {any} b
 * @returns {boolean}
 */
function isSameNodes(a, b) {
    const length = a.length;
    if (typeof length !== "number" || b.length !== length) {
        return false;
    }
    for (let i = 0; i < length; i++) {
        if (a[i] !== b[i]) {
            return false;
        }
    }
    return true;
}

/**
 * @param {string} attr
 * @param {any} value
 * @returns {asserts value is Record<string, any>}
 */
function assertAttrObject(attr, value) {
    if (!value || typeof value !== "object") {
        throw new Error(`t-att-${attr} directive expects an object`);
    }
}

/**
 * @type {FinalizationRegistry<{ refs: Set<WeakRef<HTMLElement>>, ref: WeakRef<HTMLElement> }>}
 */
const touchedRegistry = new FinalizationRegistry(({ refs, ref }) => refs.delete(ref));

/**
 * @param {{ touched: Set<WeakRef<HTMLElement>> }} entry
 * @param {HTMLElement} node
 * @returns {void}
 */
function rememberTouched(entry, node) {
    const ref = new WeakRef(node);
    entry.touched.add(ref);
    touchedRegistry.register(node, { refs: entry.touched, ref }, ref);
}

/**
 * @param {Set<WeakRef<HTMLElement>>} refs
 * @returns {void}
 */
function forgetTouched(refs) {
    for (const ref of refs) {
        touchedRegistry.unregister(ref);
    }
    refs.clear();
}

/**
 * @param {Set<WeakRef<HTMLElement>>} refs
 * @returns {HTMLElement[]}
 */
function livingNodes(refs) {
    const nodes = [];
    for (const ref of refs) {
        const node = ref.deref();
        if (node) {
            nodes.push(node);
        } else {
            refs.delete(ref);
        }
    }
    return nodes;
}

/**
 * @param {Interaction} interaction
 * @param {string} sel
 * @param {string} directive
 * @param {any} value
 * @returns {void}
 */
function assertDefinitionFunction(interaction, sel, directive, value) {
    if (typeof value !== "function") {
        throw new Error(
            `'${directive}' expects a function, got ${typeof value} ` +
                `(selector '${sel}' in interaction '${interaction.constructor.name}')`,
        );
    }
}

/**
 * @typedef {Object} DynamicAttr
 * @property {string} sel
 * @property {string} attr
 * @property {Function} definition
 * @property {WeakMap<HTMLElement, any>} initialValues
 * @property {Set<WeakRef<HTMLElement>>} touched
 */

/**
 * @typedef {Object} TOut
 * @property {string} sel
 * @property {Function} definition
 * @property {WeakMap<HTMLElement, any>} initialValue
 * @property {Set<WeakRef<HTMLElement>>} touched
 */

/**
 * @typedef {Object} ListenerRecord
 * @property {EventTarget} node
 * @property {string} event
 * @property {EventListener} handler
 * @property {AddEventListenerOptions | undefined} options
 * @property {boolean} isDetached
 * @property {() => void} forget
 * @property {EventListener} [reaper]
 */

export class Colibri {
    /**
     * @param {import("./interaction_service").InteractionService} core
     * @param {typeof Interaction} I
     * @param {HTMLElement} el
     */
    constructor(core, I, el) {
        this.el = el;
        this.isReady = false;
        this.hasStarted = false;
        this.isUpdating = false;
        this.isDestroying = false;
        this.isDestroyed = false;
        /** @type {(value?: any) => void} */
        this.signalTornDown = () => {};
        this.tornDown = new Promise((resolve) => {
            this.signalTornDown = resolve;
        });
        /** @type {DynamicAttr[]} */
        this.dynamicAttrs = [];
        /** @type {TOut[]} */
        this.tOuts = [];
        /** @type {WeakMap<HTMLElement, { source: string, nodes: ChildNode[] }>} */
        this.appliedMarkup = new WeakMap();
        /** @type {Function[]} */
        this.cleanups = [];
        /** @type {ListenerRecord[]} */
        this.listenerRecords = [];
        /**
         * @type {Map<string, Array<{ event: string, handler: EventListener, options: AddEventListenerOptions | undefined }>>}
         */
        this.listeners = new Map();
        this.dynamicNodes = new Map();
        this.core = core;
        this.interaction = new I(el, core.env, this);
        try {
            this.setupInteraction();
        } catch (error) {
            this.abortStart();
            throw error;
        }
    }

    /** @returns {void} */
    setupInteraction() {
        this.core.domEffectScope(() => this.interaction.setup());
    }

    /**
     * @param {Function} fn
     * @returns {() => void}
     */
    addCleanup(fn) {
        this.cleanups.push(fn);
        return () => {
            const index = this.cleanups.indexOf(fn);
            if (index !== -1) {
                this.cleanups.splice(index, 1);
            }
        };
    }

    /**
     * @returns {Error[]}
     */
    runCleanups() {
        const errors = [];
        while (this.cleanups.length) {
            const cleanup = /** @type {Function} */ (this.cleanups.pop());
            try {
                cleanup();
            } catch (error) {
                errors.push(error);
            }
        }
        this.listenerRecords = [];
        return errors;
    }

    /**
     * @returns {void}
     */
    destroyInteraction() {
        const errors = this.core.domEffectScope(() => {
            const errors = this.runCleanups();
            try {
                this.interaction.destroy();
            } catch (error) {
                errors.push(error);
            }
            return errors;
        });
        if (errors.length === 1) {
            throw errors[0];
        }
        if (errors.length) {
            throw new AggregateError(
                errors,
                `Some errors occured while cleaning up (in interaction '${this.interaction.constructor.name}')`,
            );
        }
    }

    /**
     * @param {Record<string, Record<string, any>> | undefined} content
     * @returns {void}
     */
    startInteraction(content) {
        this.core.domEffectScope(() => {
            if (content) {
                this.processContent(content);
                this.updateContent();
            }
            const started = /** @type {unknown} */ (this.interaction.start());
            if (started instanceof Promise) {
                const reported = started.catch((error) => this.core.reportError(error));
                this.core.trackProm(Promise.race([reported, this.tornDown]));
            }
        });
        this.hasStarted = true;
    }

    /**
     * @returns {Promise<void>}
     */
    async start() {
        try {
            const willStart = Promise.resolve(this.interaction.willStart());
            await Promise.race([willStart, this.tornDown]);
            if (this.isDestroyed || this.isDestroying) {
                willStart.catch((error) => this.core.reportError(error));
                return;
            }
            this.isReady = true;
            this.startInteraction(this.interaction.dynamicContent);
        } catch (error) {
            this.abortStart(true);
            throw error;
        }
    }

    /**
     * @param {{ withInteractionDestroy: boolean, rethrow: boolean }} options
     * @returns {void}
     */
    _teardown({ withInteractionDestroy, rethrow }) {
        if (this.isDestroyed || this.isDestroying) {
            return;
        }
        this.isDestroying = true;
        this.signalTornDown();
        /** @type {Error[]} */
        let errors = [];
        try {
            errors = this.restoreContent();
        } finally {
            this.listeners.clear();
            this.dynamicNodes.clear();
            for (const { touched } of [...this.dynamicAttrs, ...this.tOuts]) {
                forgetTouched(touched);
            }
            if (withInteractionDestroy) {
                try {
                    this.destroyInteraction();
                } catch (error) {
                    errors.push(error);
                }
            } else {
                errors.push(...this.runCleanups());
            }
            this.isDestroyed = true;
            this.isReady = false;
            if (!rethrow) {
                for (const error of errors) {
                    this.core.reportError(error);
                }
            }
        }
        if (rethrow && errors.length) {
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
     * @param {boolean} [withInteractionDestroy]
     * @returns {void}
     */
    abortStart(withInteractionDestroy = false) {
        this._teardown({ withInteractionDestroy, rethrow: false });
    }

    /**
     * Read the modifier suffixes off an event name.
     *
     * `keepInHistory` is the one modifier that decorates nothing: it opts the
     * listener out of `domEffectScope`, so its DOM changes count as the user's
     * own. Accepted as a suffix and as an option, and stripped from `options`
     * by copy -- `addEventListener` must not receive it, and the caller's
     * object is not ours to mutate.
     *
     * The decorators are returned rather than applied, so the caller can
     * install the scope UNDER them: `prevent`/`stop`/`noUpdate` must wrap the
     * scope, not sit inside it, which is where they were when the editor
     * wrapped the callback and handed the result to `addListener`.
     *
     * @param {string} event
     * @param {AddEventListenerOptions} [options]
     * @returns {{ event: string, options: AddEventListenerOptions | undefined, keepInHistory: boolean, decorators: string[] }}
     */
    _readEventModifiers(event, options) {
        let keepInHistory = false;
        if (options && "keepInHistory" in options) {
            const { keepInHistory: keep, ...rest } = /** @type {any} */ (options);
            keepInHistory = !!keep;
            options = rest;
        }
        const decorators = [];
        let groups = EVENT_MODIFIER_RE.exec(event)?.groups;
        while (groups) {
            const { suffix } = groups;
            if (suffix === "capture" || suffix === "once") {
                options = { ...options, [suffix]: true };
            } else if (suffix === "keepInHistory") {
                keepInHistory = true;
            } else {
                decorators.push(suffix);
            }
            event = groups.event;
            groups = EVENT_MODIFIER_RE.exec(event)?.groups;
        }
        return { event, options, keepInHistory, decorators };
    }

    /**
     * Wrap a listener callback into the handler that is actually registered.
     *
     * @param {Function} fn
     * @param {boolean} keepInHistory
     * @param {string[]} decorators
     * @returns {EventListener}
     */
    _buildEventHandler(fn, keepInHistory, decorators) {
        // Scope the interaction's own callback, NOT the handler built below:
        // the implicit `updateContent()` that follows it must stay outside,
        // exactly as it was when the editor wrapped the callback itself. An
        // already-built handler was scoped when it was first registered --
        // `refreshNodes` re-registers it verbatim, and wrapping twice would
        // change its identity and leak the listener.
        if (!(/** @type {any} */ (fn).isHandler) && !keepInHistory) {
            const effect = fn;
            fn = (/** @type {any[]} */ ...args) =>
                this.core.domEffectScope(() => effect.call(this.interaction, ...args));
        }
        for (const suffix of decorators) {
            fn = EVENT_MODIFIERS[suffix](fn, this);
        }
        const fnAny = /** @type {any} */ (fn);
        const handler = fnAny.isHandler
            ? fn
            : /** @param {any[]} args */ (...args) => {
                  const done = (async () => {
                      if (
                          SKIP_IMPLICIT_UPDATE !==
                          (await fn.call(this.interaction, ...args))
                      ) {
                          if (!this.isDestroyed) {
                              this.updateContent();
                          }
                      }
                  })();
                  done.catch((error) => this.core.reportError(error));
                  return done;
              };
        /** @type {any} */ (handler).isHandler = true;
        return /** @type {EventListener} */ (handler);
    }

    /**
     * @param {Iterable<EventTarget>} nodes
     * @param {string} event
     * @param {Function} fn
     * @param {AddEventListenerOptions} [options]
     * @param {string} [sel]
     * @returns {{ event: string, handler: EventListener, options: AddEventListenerOptions | undefined, remove: () => void }}
     */
    addListener(nodes, event, fn, options, sel) {
        if (typeof fn !== "function") {
            throw new Error(`Invalid listener for event '${event}' (not a function)`);
        }
        if (!this.isReady) {
            throw new Error(
                "this.addListener can only be called after the interaction is started. Maybe move the call in the start method.",
            );
        }
        let keepInHistory, decorators;
        ({ event, options, keepInHistory, decorators } = this._readEventModifiers(
            event,
            options,
        ));
        const eventListener = this._buildEventHandler(fn, keepInHistory, decorators);
        /** @type {Set<ListenerRecord>} */
        const records = new Set();
        const targets = [...nodes];
        for (const node of targets) {
            if (typeof node?.addEventListener !== "function") {
                throw new Error(
                    `Cannot listen to '${event}' on a value that is not an event target` +
                        (sel
                            ? ` (selector '${sel}' in interaction '${this.interaction.constructor.name}')`
                            : ""),
                );
            }
        }
        for (const node of targets) {
            node.addEventListener(event, eventListener, options);
            /** @type {ListenerRecord} */
            const record = {
                node,
                event,
                handler: eventListener,
                options,
                isDetached: false,
                forget: () => {},
            };
            record.forget = this.addCleanup(() => this.detachListener(record));
            if (options?.once) {
                record.reaper = () => this.forgetListener(record);
                node.addEventListener(event, record.reaper, options);
            }
            records.add(record);
            this.listenerRecords.push(record);
        }
        return {
            event,
            handler: eventListener,
            options,
            remove: () => this.removeListeners((record) => records.has(record)),
        };
    }

    /**
     * @param {ListenerRecord} record
     * @returns {void}
     */
    forgetListener(record) {
        if (record.isDetached) {
            return;
        }
        record.isDetached = true;
        record.forget();
        this.listenerRecords = this.listenerRecords.filter((r) => r !== record);
    }

    /**
     * @param {ListenerRecord} record
     * @returns {void}
     */
    detachListener(record) {
        if (!record.isDetached) {
            record.isDetached = true;
            if (record.reaper) {
                record.node.removeEventListener(
                    record.event,
                    record.reaper,
                    record.options,
                );
            }
            record.node.removeEventListener(
                record.event,
                record.handler,
                record.options,
            );
        }
    }

    /**
     * @param {(record: ListenerRecord) => boolean} predicate
     * @returns {void}
     */
    removeListeners(predicate) {
        /** @type {ListenerRecord[]} */
        const kept = [];
        for (const record of this.listenerRecords) {
            if (predicate(record)) {
                record.forget();
                this.detachListener(record);
            } else {
                kept.push(record);
            }
        }
        this.listenerRecords = kept;
    }

    /**
     * @returns {void}
     */
    refreshNodes() {
        for (const [sel, previousNodes] of this.dynamicNodes) {
            const nodes = this.getNodes(sel);
            const bindings = this.listeners.get(sel);
            if (bindings && !isSameNodes(previousNodes, nodes)) {
                const newNodes = new Set(nodes);
                const goneNodes = new Set();
                for (const node of previousNodes) {
                    if (!newNodes.delete(node)) {
                        goneNodes.add(node);
                    }
                }
                if (goneNodes.size) {
                    const handlers = new Set(bindings.map(({ handler }) => handler));
                    this.removeListeners(
                        (record) =>
                            handlers.has(record.handler) && goneNodes.has(record.node),
                    );
                }
                if (newNodes.size) {
                    for (const { event, handler, options } of bindings) {
                        this.addListener(newNodes, event, handler, options, sel);
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
        const binding = { event, handler, options };
        const bindings = this.listeners.get(sel);
        if (bindings) {
            bindings.push(binding);
        } else {
            this.listeners.set(sel, [binding]);
        }
    }

    /**
     * @param {HTMLElement} node
     * @param {import("@odoo/owl").ComponentConstructor} C
     * @param {Record<string, any>} [props]
     * @param {InsertPosition} [position]
     * @returns {() => void}
     */
    mountComponent(node, C, props, position = "beforeend") {
        const core = this.core;
        const root = core.prepareRoot(node, C, props, position);
        core.roots.push(root);
        let isRootDestroyed = false;
        let forget = () => {};
        const destroy = () => {
            if (!isRootDestroyed) {
                isRootDestroyed = true;
                forget();
                core.forgetRoot(root);
                root.destroy();
            }
        };
        forget = this.addCleanup(destroy);
        core.trackProm(
            root.mount().catch((error) => {
                if (!isRootDestroyed) {
                    core.reportError(error);
                }
            }),
        );
        return destroy;
    }

    /**
     * @param {HTMLElement} el
     * @param {any} value
     * @param {any} [initialValue]
     * @param {boolean} [restoring]
     * @returns {void}
     */
    applyTOut(el, value, initialValue, restoring = false) {
        return this.core.domEffectScope(() => {
            if (value === INITIAL_VALUE) {
                value = initialValue;
            }
            const html = value instanceof Markup ? value.toString() : null;
            if (html === null) {
                if (isSameTextContent(el, value)) {
                    return;
                }
            } else {
                const applied = this.appliedMarkup.get(el);
                if (
                    applied?.source === html &&
                    isSameNodes(el.childNodes, applied.nodes)
                ) {
                    return;
                }
                if (el.innerHTML === html) {
                    this.appliedMarkup.set(el, {
                        source: html,
                        nodes: [...el.childNodes],
                    });
                    return;
                }
            }
            const interactions = this.core;
            const stopTargets = () => {
                for (const node of [...el.children]) {
                    interactions.stopInteractions(/** @type {HTMLElement} */ (node));
                }
            };
            if (html !== null) {
                stopTargets();
                el.innerHTML = html;
                this.appliedMarkup.set(el, { source: html, nodes: [...el.childNodes] });
                if (!restoring) {
                    interactions.startInteractions(el);
                    this.refreshNodes();
                }
            } else {
                this.appliedMarkup.delete(el);
                if (el.children.length) {
                    stopTargets();
                }
                el.textContent = value;
            }
        });
    }

    /**
     * @param {HTMLElement} el
     * @param {string} attr
     * @param {any} value
     * @param {any} [initialValue]
     * @returns {void}
     */
    applyAttr(el, attr, value, initialValue) {
        return this.core.domEffectScope(() => {
            if (attr === "class") {
                assertAttrObject(attr, value);
                for (const cl of Object.keys(value)) {
                    const toApply = value[cl];
                    for (const c of splitClassNames(cl)) {
                        const apply =
                            toApply === INITIAL_VALUE ? initialValue[c] : toApply;
                        el.classList.toggle(c, apply || false);
                    }
                }
            } else if (attr === "style") {
                assertAttrObject(attr, value);
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
                            el.style.setProperty(
                                prop,
                                style.slice(0, -11),
                                "important",
                            );
                        } else {
                            el.style.setProperty(prop, style);
                        }
                    }
                }
            } else {
                if (value === INITIAL_VALUE) {
                    value = initialValue;
                }
                if (value === false || value === undefined || value === null) {
                    if (el.hasAttribute(attr)) {
                        el.removeAttribute(attr);
                    }
                } else {
                    const next = value === true ? attr : String(value);
                    if (el.getAttribute(attr) !== next) {
                        el.setAttribute(attr, next);
                    }
                }
            }
        });
    }

    /**
     * @param {string} sel
     * @returns {Iterable<HTMLElement>}
     */
    getNodes(sel) {
        const selectors = this.interaction.dynamicSelectors;
        if (Object.hasOwn(selectors, sel)) {
            return toEventTargets(selectors[sel]() || null);
        }
        return this.interaction.el.querySelectorAll(sel);
    }

    /**
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
                    const { event, handler, options } = this.addListener(
                        nodes,
                        directive.slice(5),
                        value,
                        undefined,
                        sel,
                    );
                    this.mapSelectorToListeners(sel, event, handler, options);
                } else if (directive.startsWith("t-att-")) {
                    assertDefinitionFunction(this.interaction, sel, directive, value);
                    this.dynamicAttrs.push({
                        sel,
                        attr: directive.slice(6),
                        definition: value,
                        initialValues: new WeakMap(),
                        touched: new Set(),
                    });
                } else if (directive === "t-out") {
                    assertDefinitionFunction(this.interaction, sel, directive, value);
                    this.tOuts.push({
                        sel,
                        definition: value,
                        initialValue: new WeakMap(),
                        touched: new Set(),
                    });
                } else if (directive === "t-component") {
                    if (Object.prototype.isPrototypeOf.call(Component, value)) {
                        for (const node of nodes) {
                            this.mountComponent(node, value);
                        }
                    } else {
                        for (const node of nodes) {
                            const [C, props, pos] =
                                /**
                                 * @type {[import("@odoo/owl").ComponentConstructor, Record<string, any>?, InsertPosition?]}
                                 */ (value(node));
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
     * @returns {void}
     */
    updateContent() {
        if (this.isDestroyed) {
            throw new Error("Cannot update the content of a destroyed interaction");
        }
        if (!this.isReady) {
            throw new Error(
                "Cannot update the content of an interaction that has not started yet (dynamic content is applied once willStart resolves)",
            );
        }
        if (this.isUpdating) {
            throw new Error(
                "updateContent should not be called while interaction is updating",
            );
        }
        this.isUpdating = true;
        /** @type {Array<{ error: Error, description: string }>} */
        const errors = [];
        try {
            this.applyContent(errors);
        } finally {
            this.isUpdating = false;
        }
        if (errors.length) {
            const name = this.interaction.constructor.name;
            /** @param {{ error: Error, description: string }} entry */
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
     * @param {HTMLElement} node
     * @param {string} attr
     * @param {any} value
     * @param {WeakMap<HTMLElement, any>} initialValues
     * @returns {any}
     */
    captureInitialAttr(node, attr, value, initialValues) {
        if (attr !== "class" && attr !== "style") {
            if (!initialValues.has(node)) {
                initialValues.set(node, node.getAttribute(attr));
            }
            return initialValues.get(node);
        }
        assertAttrObject(attr, value);
        let initial = initialValues.get(node);
        if (!initial) {
            initial = {};
            initialValues.set(node, initial);
        }
        for (const key of Object.keys(value)) {
            for (const name of attr === "class" ? splitClassNames(key) : [key]) {
                if (name in initial) {
                    continue;
                }
                if (attr === "class") {
                    initial[name] = node.classList.contains(name);
                } else {
                    const propertyValue = node.style.getPropertyValue(name);
                    const priority = node.style.getPropertyPriority(name);
                    initial[name] = propertyValue
                        ? propertyValue + (priority ? ` !${priority}` : "")
                        : undefined;
                }
            }
        }
        return initial;
    }

    /**
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
        for (const tOut of this.tOuts) {
            const { sel, definition, initialValue } = tOut;
            for (const node of this.dynamicNodes.get(sel) || []) {
                try {
                    if (!initialValue.has(node)) {
                        rememberTouched(tOut, node);
                        initialValue.set(
                            node,
                            node.children.length
                                ? markup(node.innerHTML)
                                : node.textContent,
                        );
                    }
                    this.applyTOut(
                        node,
                        definition.call(interaction, node),
                        initialValue.get(node),
                    );
                } catch (error) {
                    errors.push({
                        error,
                        description: `'t-out' content (selector '${sel}')`,
                    });
                }
            }
        }
        for (const dynamicAttr of this.dynamicAttrs) {
            const { sel, attr, definition, initialValues } = dynamicAttr;
            for (const node of this.dynamicNodes.get(sel) || []) {
                try {
                    const value = definition.call(interaction, node);
                    if (!initialValues.has(node)) {
                        rememberTouched(dynamicAttr, node);
                    }
                    const initial = this.captureInitialAttr(
                        node,
                        attr,
                        value,
                        initialValues,
                    );
                    this.applyAttr(node, attr, value, initial);
                } catch (error) {
                    errors.push({
                        error,
                        description: `dynamic attribute '${attr}' (selector '${sel}')`,
                    });
                }
            }
        }
    }

    /**
     * @returns {Error[]}
     */
    restoreContent() {
        const errors = [];
        for (const { attr, initialValues, touched } of this.dynamicAttrs) {
            for (const node of livingNodes(touched)) {
                if (initialValues.has(node)) {
                    try {
                        this.applyAttr(node, attr, initialValues.get(node));
                    } catch (error) {
                        errors.push(error);
                    }
                }
            }
        }
        for (const { initialValue, touched } of this.tOuts) {
            for (const node of livingNodes(touched)) {
                if (initialValue.has(node)) {
                    try {
                        this.applyTOut(node, initialValue.get(node), null, true);
                    } catch (error) {
                        errors.push(error);
                    }
                }
            }
        }
        return errors;
    }

    /**
     * @returns {void}
     */
    destroy() {
        this._teardown({ withInteractionDestroy: true, rethrow: true });
    }

    /**
     * @param {Interaction} interaction
     * @param {Function} fn
     * @returns {Function}
     */
    bindDeferred(interaction, fn) {
        const bound = fn.bind(interaction);
        return (/** @type {any[]} */ ...args) =>
            this.core.domEffectScope(() => bound(...args));
    }
}
