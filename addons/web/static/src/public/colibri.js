// @ts-check
/** @odoo-module native */

/** @module @web/public/colibri - Mini-framework runtime that manages Interaction lifecycles, dynamic content, and event bindings for public pages */

/** @import { Interaction } from "@web/public/interaction" */

import { Component, markup } from "@odoo/owl";

const Markup = markup("").constructor;

export const INITIAL_VALUE = Symbol("initial value");
export const SKIP_IMPLICIT_UPDATE = Symbol();

const EVENT_MODIFIER_RE =
    /^(?<event>.*)\.(?<suffix>prevent|stop|capture|once|noUpdate|withTarget)$/;

/**
 * Wrappers for the `.prevent`, `.stop`, `.noUpdate` and `.withTarget` event
 * suffixes. `.capture` and `.once` are listener options rather than behaviour,
 * and are handled directly in `Colibri.addListener`.
 *
 * @type {Record<string, (fn: Function, colibri: Colibri) => Function>}
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
    // awaited, so that an async handler's rejection still reaches the error
    // channel: dropping the returned promise made `.noUpdate` the one suffix
    // that turned a failing handler into an unhandled rejection
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
 * Normalizes anything a dynamic selector (or `Interaction.addListener`) may
 * yield into an iterable of event targets.
 *
 * A single node is always wrapped rather than iterated: `<form>` and `<select>`
 * are themselves iterable (over their controls / options), so an iterability
 * test alone would silently fan a directive out over their children. `nodeType`
 * is duck-typed rather than `instanceof Node` so the check also holds for nodes
 * coming from another realm (the website builder's iframe).
 *
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
 * @param {string} names whitespace-separated class names
 * @returns {string[]}
 */
function splitClassNames(names) {
    return names.split(/\s+/).filter(Boolean);
}

/**
 * True when `el` already holds exactly what `el.textContent = value` would put
 * there: nothing at all for an empty value, a lone text node holding it
 * otherwise. Read from the DOM rather than from a cache, so content another
 * hand has changed is still rewritten.
 *
 * @param {HTMLElement} el
 * @param {any} value
 * @returns {boolean}
 */
function isSameTextContent(el, value) {
    // measured, not assumed: `textContent` is a nullable IDL attribute, so it
    // stores the empty string for BOTH null and undefined, and the plain string
    // conversion for everything else — `String(undefined)` would have made a
    // node already reading "undefined" look like a match and freeze it there
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
 * Yields the still-reachable nodes of a set of weak references, dropping the
 * references whose node is gone.
 *
 * Directives are restored from what they have touched rather than from what
 * their selector matches at destroy time: a node that left the match set — a
 * dynamic selector now returning another element, a class another handler
 * toggled — kept whatever the interaction had applied to it for good, since
 * destroy() puts back exactly what it can still see. The references are weak
 * because most departed nodes leave the document too, and a strong set would
 * pin every one of them for the interaction's lifetime.
 *
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
 * A `t-att-*` / `t-out` entry is evaluated per node on every update, so a value
 * that is not callable fails once per node per update, wrapped in the generic
 * "could not update" error. Rejecting it where it is declared names the entry
 * once, and at a point where the stack still points at the interaction.
 *
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
 * @typedef {Object} ListenerRecord
 * @property {EventTarget} node
 * @property {string} event
 * @property {EventListener} handler
 * @property {AddEventListenerOptions | undefined} options
 * @property {boolean} isDetached
 * @property {() => void} forget drops this listener's entry from the cleanup list
 * @property {EventListener} [reaper] one-shot listener that clears this record's
 *  bookkeeping once a `once` listener has fired
 */

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
        this.isDestroying = false;
        this.isDestroyed = false;
        this.dynamicAttrs = [];
        this.tOuts = [];
        // the markup last written to each node by ANY t-out of this
        // interaction, shared rather than kept per entry: two entries whose
        // selectors both match a node legitimately overwrite each other, and a
        // per-entry cache made each of them skip on the other's write, so the
        // node froze on whichever had last changed instead of on the last
        // entry. The DOM cannot answer the question by itself — interactions
        // started in the inserted subtree mutate it immediately after, so
        // re-serialising the node would never match what was written.
        /** @type {WeakMap<HTMLElement, string>} */
        this.appliedMarkup = new WeakMap();
        this.cleanups = [];
        /** @type {ListenerRecord[]} */
        this.listenerRecords = [];
        /** @type {Map<string, Array<{ event: string, handler: EventListener, options: AddEventListenerOptions | undefined }>>} */
        this.listeners = new Map();
        this.dynamicNodes = new Map();
        this.core = core;
        this.interaction = new I(el, core.env, this);
        try {
            this.setupInteraction();
        } catch (error) {
            // setup() may already have registered cleanups or inserted nodes
            // before throwing, and the caller discards this Colibri, so nothing
            // else would ever undo them.
            this.abortStart();
            throw error;
        }
    }

    /** @returns {void} */
    setupInteraction() {
        this.interaction.setup();
    }

    /**
     * Registers a teardown step. Returns a function that forgets it again,
     * so that a step which has already run (a fired timeout, an early manual
     * destroy) does not accumulate in the cleanup list for the whole life of
     * the interaction.
     *
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
     * Runs every registered teardown step, most recent first — listener
     * removals are part of that list, so a cleanup still sees the listeners
     * registered before it. A throwing step never skips the ones that follow:
     * a single failing cleanup used to leave every remaining listener attached.
     *
     * The list is drained rather than iterated, because a step may edit it
     * while it runs: every `forget()` splices an entry out, and `mountComponent`
     * registers a step that forgets itself. Walking a reversed copy-in-place
     * with a for..of meant that splice shifted the remaining entries left under
     * the iterator, silently skipping the step registered just before the mount.
     *
     * @returns {Error[]} the errors raised by the steps
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
     * Tears the interaction down: every teardown step, then its own `destroy`.
     *
     * @returns {void}
     */
    destroyInteraction() {
        const errors = this.runCleanups();
        try {
            this.interaction.destroy();
        } catch (error) {
            errors.push(error);
        }
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
     * A failure on either leg discards this Colibri — the service drops it from
     * the list it destroys — so the framework has to undo its own work here or
     * nobody ever will: `setup()` may have inserted nodes and registered
     * cleanups, and `startInteraction` attaches every dynamicContent listener
     * before `interaction.start()` gets to throw. Those listeners used to stay
     * bound, on an interaction that no longer exists, for the life of the page.
     *
     * @returns {Promise<void>}
     */
    async start() {
        try {
            await this.interaction.willStart();
            if (this.isDestroyed) {
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
     * Tears down a Colibri that never finished starting: the dynamic content
     * applied so far is restored, then every teardown step runs.
     *
     * `withInteractionDestroy` says whether the interaction's own `destroy()`
     * runs too, and it turns on whether `setup()` completed. It did not, in the
     * constructor's case, so `destroy()` would meet an instance whose own
     * initialisation never finished. It did on the `start()` path — and there
     * the framework already calls `destroy()` on a set-up-but-not-started
     * interaction whenever a `stopInteractions()` lands while `willStart()` is
     * still pending, so this is an established state, not a new one. It is also
     * the only teardown 26 interactions in this codebase have: they clear
     * intervals, disconnect observers and destroy chart/player objects there,
     * not through `registerCleanup`.
     *
     * Teardown failures are reported rather than thrown: the caller is already
     * propagating the failure that caused the abort, which is the interesting
     * one.
     *
     * @param {boolean} [withInteractionDestroy]
     * @returns {void}
     */
    abortStart(withInteractionDestroy = false) {
        if (this.isDestroyed || this.isDestroying) {
            return;
        }
        this.isDestroying = true;
        /** @type {Error[]} */
        let errors = [];
        // same guarantee as destroy(): the teardown runs even if restoring the
        // content somehow fails, since nothing will ever revisit this Colibri
        try {
            errors = this.restoreContent();
        } finally {
            if (withInteractionDestroy) {
                try {
                    this.destroyInteraction();
                } catch (error) {
                    errors.push(error);
                }
            } else {
                errors.push(...this.runCleanups());
            }
            this.listeners.clear();
            this.dynamicNodes.clear();
            for (const error of errors) {
                this.core.reportError(error);
            }
            this.core = null;
            this.isDestroyed = true;
            this.isReady = false;
        }
    }

    /**
     * Attaches an event listener to nodes, with optional modifier suffixes
     * (.prevent, .stop, .once, .capture, .noUpdate, .withTarget).
     *
     * @param {Iterable<EventTarget>} nodes
     * @param {string} event event name, optionally with dot-suffixed modifiers
     * @param {Function} fn
     * @param {AddEventListenerOptions} [options]
     * @param {string} [sel] dynamicContent selector owning the listener, for
     *  diagnostics only — nothing here depends on it, so a patch of this method
     *  (the website builder wraps it) may forward only the documented arguments
     *  without breaking listener bookkeeping
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
        let groups = EVENT_MODIFIER_RE.exec(event)?.groups;
        while (groups) {
            const { suffix } = groups;
            if (suffix === "capture" || suffix === "once") {
                // a fresh object: mutating the caller's would leak the flag to
                // every other listener sharing that options object
                options = { ...options, [suffix]: true };
            } else {
                fn = EVENT_MODIFIERS[suffix](fn, this);
            }
            event = groups.event;
            groups = EVENT_MODIFIER_RE.exec(event)?.groups;
        }
        const fnAny = /** @type {any} */ (fn);
        const handler = fnAny.isHandler
            ? fn
            : (...args) => {
                  // the DOM drops an event listener's return value, so a
                  // throwing handler — or a t-att definition that throws in
                  // the implicit updateContent — only ever surfaced as an
                  // unhandled rejection, never through the error channel
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
                  done.catch((error) =>
                      this.interaction.services["public.interactions"].reportError(
                          error,
                      ),
                  );
                  return done;
              };
        /** @type {any} */ (handler).isHandler = true;
        const eventListener = /** @type {EventListener} */ (handler);
        /** @type {Set<ListenerRecord>} */
        const records = new Set();
        for (const node of nodes) {
            if (typeof node?.addEventListener !== "function") {
                throw new Error(
                    `Cannot listen to '${event}' on a value that is not an event target` +
                        (sel
                            ? ` (selector '${sel}' in interaction '${this.interaction.constructor.name}')`
                            : ""),
                );
            }
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
            // detaching is a teardown step like any other, so it takes its
            // place in the ordered cleanup list rather than in a parallel one
            record.forget = this.addCleanup(() => this.detachListener(record));
            if (options?.once) {
                // the DOM drops a `once` listener the moment it fires, but its
                // bookkeeping stayed behind: the record, the teardown step, and
                // through them the handler's whole closure. An interaction that
                // arms a one-shot listener on every cycle (the website popup
                // re-arms two on each open) grew all three without bound, and
                // pinned every element those closures had captured. A second
                // one-shot listener, registered after it, reaps the first.
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
     * Drops a listener's bookkeeping, for one the DOM has already dropped by
     * itself. Leaves the DOM alone: a fired `once` listener, and the reaper
     * that observed it, are both gone from the node already.
     *
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
     * Detaches every listener matching `predicate`, forgetting both its record
     * and its cleanup entry so that bookkeeping and the DOM cannot drift apart.
     * Dropping the whole node's cleanups instead — as the departed-node pruning
     * used to — silently unregistered the removal of listeners bound to that
     * same node through another selector, which then outlived the interaction.
     *
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
     * Re-evaluates every dynamic selector: listeners of departed nodes are
     * detached and listeners of newly matched nodes are attached.
     *
     * Departed listeners are matched by handler identity rather than by the
     * selector they were registered under: `addListener` is a patch point, and
     * a patch forwarding only its documented arguments left every record
     * untagged, so nothing here could ever detach them again. The handler of a
     * (selector, event) pair is unique — `addListener` wraps each definition in
     * a fresh closure — and stable, since the wrapper is passed through
     * unchanged when it comes back for a newly matched node.
     *
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
     * Records a selector's listener so that `refreshNodes` can re-bind it to
     * newly matched nodes and detach it from departed ones.
     *
     * A list and not a map keyed by event name: several directives on one
     * selector legitimately share an event (`t-on-click` alongside
     * `t-on-click.capture`, or `t-on-click.prevent`), and keying by name let
     * the last one registered evict the others — they were then never re-bound
     * to a newly matched node, and, being absent from the handler set built
     * here, never detached from a departed one either.
     *
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
     * Mounts an OWL component inside `node` and registers cleanup. The mount is
     * tracked by the service so that `isReady` — and therefore the page's
     * `is-ready` flag that tours and the website builder wait on — accounts for
     * sub-components too. A mount failure is reported but does not reject
     * `isReady`, so one broken component cannot mark a whole page unready.
     *
     * The root joins the service's list like any other, so that stopping the
     * subtree it lives in destroys it. Left out of that list, a component
     * mounted on a descendant survived the teardown of everything around it:
     * its `<owl-root>` stayed in the page and the component kept running,
     * subscriptions and all, until the interaction that mounted it happened to
     * be stopped in its turn.
     *
     * @param {HTMLElement} node
     * @param {import("@odoo/owl").ComponentConstructor} C
     * @param {Record<string, any>} [props]
     * @param {InsertPosition} [position]
     * @returns {() => void} cleanup function, safe to call more than once
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
        // registered before the mount: `prepareRoot` has already put a host
        // element in the document, and a mount that throws synchronously would
        // otherwise leave it there with nothing left to remove it
        forget = this.addCleanup(destroy);
        core._trackProm(
            root.mount().catch((error) => {
                if (!isRootDestroyed) {
                    core.reportError(error);
                }
            }),
        );
        return destroy;
    }

    /**
     * Applies a t-out directive: sets textContent or innerHTML for Markup values.
     *
     * A write that would change nothing is skipped. This is not an
     * optimisation: the Markup branch is not a write but a rebuild — every
     * interaction in the subtree is stopped, the markup is re-parsed, and the
     * result is rescanned — so re-running it for an unchanged value destroyed
     * and restarted nested interactions on every single update, discarding
     * their state along with the focus, the selection and the scroll position
     * of whatever they held. The text branch is milder but replaces the text
     * node, which collapses a selection the visitor is making.
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
        const html = value instanceof Markup ? value.toString() : null;
        if (
            html === null
                ? isSameTextContent(el, value)
                : this.appliedMarkup.get(el) === html
        ) {
            return;
        }
        const interactions = this.core.env.services["public.interactions"];
        // `el.children` is live and stopping an interaction may detach nodes
        // (an insert()/renderAt() cleanup does), which would make the iteration
        // skip every other sibling. Snapshot before touching anything.
        //
        // The children and not `el` itself, even when `el` is not this
        // interaction's root: a t-out owns the *content* of its node, and an
        // interaction rooted on that node is not part of the markup being
        // replaced. Stopping it left it destroyed for good on the text branch,
        // which never rescans, and restarted it from scratch on every update
        // on the Markup one.
        const stopTargets = () => {
            for (const node of [...el.children]) {
                interactions.stopInteractions(node);
            }
        };
        if (html !== null) {
            stopTargets();
            el.innerHTML = html;
            this.appliedMarkup.set(el, html);
            if (!restoring) {
                // one scan of the whole subtree: the service already skips the
                // interactions still active on `el` itself, so scanning per
                // child only multiplied the cost by the number of children
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
            assertAttrObject(attr, value);
            for (const cl of Object.keys(value)) {
                const toApply = value[cl];
                // a key holding several class names may be padded or
                // double-spaced; an empty token makes classList.toggle throw
                for (const c of splitClassNames(cl)) {
                    const apply = toApply === INITIAL_VALUE ? initialValue[c] : toApply;
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
            // `setAttribute` queues a mutation record even when it writes the
            // value that is already there, and every definition is re-evaluated
            // on every update: an interaction with a stable t-att-* fed every
            // MutationObserver watching the page one spurious record per
            // attribute per event. Not the website builder's history — it wraps
            // this method in `ignoreDOMMutations` — but every other observer,
            // and the write itself is pointless either way.
            // `classList.toggle(force)` and `style.setProperty` were measured to
            // skip a write that changes nothing already; `setAttribute` is the
            // only branch that needed the guard.
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
            return toEventTargets(selectors[sel]() || null);
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
     * Captures the value an attribute had before the interaction first touched
     * it, so that destroy() can put it back.
     *
     * A `t-att-class` / `t-att-style` definition does not have to yield the
     * same keys every time (`() => this.isOpen ? { open: true } : { shut: true }`
     * is a normal definition), and destroy() restores exactly what was
     * captured: capturing once, from the first evaluation, left every key
     * introduced later applied for good. Keys are therefore topped up as they
     * appear — a key seen for the first time has by definition not been touched
     * by this directive yet, so the node still holds its original value.
     *
     * @param {HTMLElement} node
     * @param {string} attr
     * @param {any} value the definition's current value, whose keys tell which
     *  classes / style properties are in play
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
        for (const { sel, attr, definition, initialValues, touched } of this
            .dynamicAttrs) {
            for (const node of this.dynamicNodes.get(sel) || []) {
                try {
                    const value = definition.call(interaction, node);
                    if (!initialValues.has(node)) {
                        touched.add(new WeakRef(node));
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
                        description: `dynamic attribute '${attr}'`,
                    });
                }
            }
        }
        for (const { sel, definition, initialValue, touched } of this.tOuts) {
            for (const node of this.dynamicNodes.get(sel) || []) {
                try {
                    if (!initialValue.has(node)) {
                        touched.add(new WeakRef(node));
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
    }

    /**
     * Puts every node this interaction's `t-att-*` and `t-out` directives have
     * touched back to the value it held before, collecting failures instead of
     * aborting so that one unrestorable node does not strand the rest.
     *
     * @returns {Error[]} the errors raised while restoring
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
     * Restores all dynamic attributes and t-out values to their initial state,
     * removes event listeners, destroys the interaction, and marks this
     * Colibri as destroyed.
     *
     * @returns {void}
     */
    destroy() {
        // `isDestroying` and not just `isDestroyed`: a teardown step may stop
        // interactions of its own (removing an inserted subtree does), and the
        // service still lists this one until its own destroy() returns, so a
        // re-entrant call would run the whole teardown a second time
        if (this.isDestroyed || this.isDestroying) {
            return;
        }
        this.isDestroying = true;
        /** @type {Error[]} */
        let errors = [];
        // the interaction is torn down even if restoring its content somehow
        // fails: a Colibri left half-destroyed is dropped from the service's
        // list all the same, so it would never get a second chance
        try {
            errors = this.restoreContent();
        } finally {
            this.listeners.clear();
            this.dynamicNodes.clear();
            try {
                this.destroyInteraction();
            } catch (error) {
                errors.push(error);
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
