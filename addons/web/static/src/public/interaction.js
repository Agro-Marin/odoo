// @ts-check
/** @odoo-module native */

/** @module @web/public/interaction - Base class for public page interactions with selector matching, dynamic content, and service access */

import { renderToFragment } from "@web/core/utils/render";
import { debounce, throttleForAnimation } from "@web/core/utils/timing";

import { INITIAL_VALUE, SKIP_IMPLICIT_UPDATE, toEventTargets } from "./colibri.js";
import { makeAsyncHandler, makeButtonHandler } from "./minimal_dom.js";
/**
 * Base class for interactions: web-framework integration (env/services), a
 * defined lifecycle, dynamic content, and helpers for common tasks like
 * adding DOM listeners or waiting on async work.
 *
 * Interactions aren't destroyed in the standard workflow (visiting the
 * website), but can be (e.g. switching to "edit" mode) — clean up after
 * yourself.
 */

/**
 * Adapts a debounced / throttled function to the dynamic-content protocol: the
 * wrapped call runs later and applies the content itself, so the handler must
 * opt out of the implicit update the framework would otherwise do on return.
 *
 * Opting out also cuts the deferred call off from the framework's error
 * channel — nothing awaits it — so its failures are routed explicitly. Without
 * this, a throwing debounced handler was reported as a bare unhandled
 * rejection, naming neither the interaction nor the event.
 *
 * @param {Interaction} interaction
 * @param {((...args: any[]) => any) & { cancel: () => void }} fn
 * @returns {((...args: any[]) => symbol) & { cancel: () => void }}
 */
function asDeferredHandler(interaction, fn) {
    const handler = (...args) => {
        Promise.resolve(fn(...args)).catch((error) =>
            interaction.services["public.interactions"].reportError(error),
        );
        return SKIP_IMPLICIT_UPDATE;
    };
    // the debug-facing name is worth keeping across the wrapper
    Object.defineProperty(handler, "name", { value: fn.name, configurable: true });
    handler.cancel = fn.cancel;
    return handler;
}

export class Interaction {
    /**
     * CSS selector for the html elements targeted by this interaction. An
     * instance is created for each match when the website framework starts.
     *
     * @type {string}
     */
    static selector = "";

    /**
     * Filters elements matched by `selector` to those containing at least
     * one element matching `selectorHas`. Equivalent to the `:has()`
     * pseudo-selector, used instead because `:has` support is inconsistent
     * across browsers.
     *
     * @type {string}
     */
    static selectorHas = "";

    /**
     * Similar to `selectorHas` but equivalent to `:not(:has(...))`. Can be
     * combined with `selectorHas`.
     *
     * @type {string}
     */
    static selectorNotHas = "";

    /**
     * Constant to reset dynamicContent t-att-* and t-out.
     */
    static INITIAL_VALUE = INITIAL_VALUE;

    /**
     * A dynamic selector may return a falsy value (e.g. a missed
     * querySelector); the directive is then ignored.
     *
     * @type {Object.<string, Function>}
     */
    dynamicSelectors = {
        _root: () => this.el,
        _body: () => this.el.ownerDocument.body,
        // the element's own view, so that an interaction running against
        // another realm's document (the builder's iframe) agrees with _document
        // and _body. A document with no view at all (one built by
        // createHTMLDocument or DOMParser) has no `defaultView`; this one falls
        // back to the running window rather than to nothing, so that a
        // directive written against `_window` still binds somewhere listenable
        _window: () => this.el.ownerDocument.defaultView || window,
        _document: () => this.el.ownerDocument,
    };

    /**
     * The dynamic content of an interaction is an object describing the set of
     * "dynamic elements" managed by the framework: event handlers, dynamic
     * attributes, dynamic content, sub components.
     *
     * Its syntax looks like the following:
     * dynamicContent = {
     *      ".some-selector": { "t-on-click": (ev) => this.onClick(ev) },
     *      ".some-other-selector": {
     *          "t-att-class": () => ({ "some-class": true }),
     *          "t-att-style": () => ({ property: value }),
     *          "t-att-other-attribute": () => value,
     *          "t-out": () => value,
     *      },
     *      _root: { "t-component": () => [Component, { someProp: "value" }] },
     * }
     *
     * A selector is either a standard css selector, or a special keyword
     * (see dynamicSelectors: _body, _root, _document, _window)
     *
     * Accepted directives include: t-on-, t-att-, t-out and t-component
     *
     * A falsy value on a class or style property will remove it.
     * On others attributes:
     * - `false`, `undefined` or `null` remove it
     * - other falsy values (`""`, `0`) are applied as such (`required=""`)
     * - boolean `true` is applied as the attribute's name
     *   (e.g. `{ "t-att-required": () => true }` applies `required="required"`)
     *
     * t-att-* and t-out directives also accept `Interaction.INITIAL_VALUE`,
     * which resets them to the value they had before the interaction's start.
     *
     * This is not owl! Similar syntax for familiarity, but semantics differ.
     *
     * @type {Object}
     */
    dynamicContent = {};

    /**
     * The constructor is not supposed to be defined in a subclass. Use setup
     * instead.
     *
     * @param {HTMLElement} el
     * @param {import("@web/env").OdooEnv} env
     * @param {Object} metadata
     */
    constructor(el, env, metadata) {
        this.__colibri__ = metadata;
        this.el = el;
        this.env = env;
        /** @type {import("services").ServiceFactories} */
        this.services = env.services;
    }

    /**
     * Returns true if the interaction has been started (so, just before the
     * start method is called)
     */
    get isReady() {
        return this.__colibri__.isReady;
    }

    get isDestroyed() {
        return this.__colibri__.isDestroyed;
    }

    /**
     * This is the standard constructor method. This is the proper place to
     * initialize everything needed by the interaction. The el element is
     * available and can be used. Services are ready and available as well.
     */
    setup() {}

    /**
     * If the interaction needs some asynchronous work to be ready, it should
     * be done here. The website framework will wait for this method to complete
     * before applying the dynamic content (event handlers, ...).
     */
    async willStart() {}

    /**
     * The start function when we need to execute some code once the interaction
     * is ready. It is the equivalent to the "mounted" owl lifecycle hook. At
     * this point, event handlers have been attached.
     */
    start() {}

    /**
     * All side effects done should be cleaned up here. As with other
     * lifecycle methods, calling super.destroy is unnecessary unless you
     * inherit from a concrete subclass.
     */
    destroy() {}

    /**
     * Applies the dynamic content description to the dom synchronously (e.g.
     * dynamic attributes defined with t-att-). Already called after each
     * event handler and by most other helpers, so rarely needed directly.
     */
    updateContent() {
        this.__colibri__.updateContent();
    }

    /**
     * Wraps a promise into one that settles only while the instance is alive,
     * and that calls `updateContent` once the calling code has acted.
     *
     * Neither outcome settles after a destroy: the point of `await
     * this.waitFor(...)` is that what follows it never runs against a destroyed
     * interaction, and a rejection is no exception — a `catch` block touches
     * the same dead instance a `then` block would. The error goes to the
     * service's channel instead of being dropped.
     */
    waitFor(promise = Promise.resolve()) {
        const prom = new Promise((resolve, reject) => {
            const updateAfterCaller = () => {
                if (this.isReady && !this.isDestroyed) {
                    try {
                        this.updateContent();
                    } catch (error) {
                        // this update hangs off a promise nobody holds, so a
                        // failing definition surfaced as an unhandled rejection
                        // naming neither the interaction nor the directive
                        this.services["public.interactions"].reportError(error);
                    }
                }
            };
            promise.then(
                (result) => {
                    if (this.isDestroyed) {
                        return;
                    }
                    resolve(result);
                    prom.then(updateAfterCaller);
                },
                (error) => {
                    if (this.isDestroyed) {
                        this.services["public.interactions"].reportError(error);
                        return;
                    }
                    reject(error);
                    prom.catch(updateAfterCaller);
                },
            );
        });
        return prom;
    }

    /**
     * Mechanism to handle context-specific protection of a specific
     * chunk of synchronous code after returning from an asynchronous one.
     * This method returns a function that will run the wrapped function in a
     * protected context when it is called.
     * This should typically be used around code that follows an
     * await this.waitFor(...).
     *
     * Example use-case: website builder's edit-mode disables the history
     * observer to ignore the changes done by interactions.
     *
     * A listener involving async code would then look like this:
     * async onClick() {
     *     // Code before await is protected
     *     const result = await this.waitFor(...);
     *     // Code here is not protected anymore
     *     // Render variables can be updated because updateContent will run
     *     // after the handler in a protected state
     *     this.stuffUsedByTAtt = result.stuffUsedByTAtt;
     *     this.protectSyncAfterAsync(() => {
     *         // Code here is protected again, DOM can be updated
     *         doStuff(this.el);
     *     })();
     * }
     *
     * @param {Function} fn function that needs to run in a protected context
     * @return {Function} protected function
     */
    protectSyncAfterAsync(fn) {
        return this.__colibri__.protectSyncAfterAsync(
            this,
            "protectSyncAfterAsync",
            fn,
        );
    }

    /**
     * Runs a callback scheduled for later and applies the dynamic content,
     * unless the interaction was destroyed in the meantime.
     *
     * Failures go to the service's error channel: these callbacks run from a
     * timer or a frame callback, with no caller left to catch them, so an
     * exception escaped as a bare uncaught error instead of being reported like
     * every other interaction failure.
     *
     * @param {Function} fn
     * @returns {void}
     */
    _runDeferred(fn) {
        if (this.isDestroyed) {
            return;
        }
        try {
            fn.call(this);
            if (this.isReady) {
                this.updateContent();
            }
        } catch (error) {
            this.services["public.interactions"].reportError(error);
        }
    }

    /**
     * Wait for a specific timeout, then execute the given function (unless the
     * interaction has been destroyed). The dynamic content is then applied.
     * The timer is cancelled on destroy, so a pending long delay keeps neither
     * the callback's closure nor a scheduled task alive.
     */
    waitForTimeout(fn, delay) {
        fn = this.__colibri__.protectSyncAfterAsync(this, "waitForTimeout", fn);
        let forget;
        const timer = setTimeout(() => {
            forget();
            this._runDeferred(fn);
        }, delay);
        forget = this.__colibri__.addCleanup(() => clearTimeout(timer));
        return timer;
    }

    /**
     * Wait for a animation frame, then execute the given function (unless the
     * interaction has been destroyed). The dynamic content is then applied.
     * The frame is cancelled on destroy.
     */
    waitForAnimationFrame(fn) {
        fn = this.__colibri__.protectSyncAfterAsync(this, "waitForAnimationFrame", fn);
        let forget;
        const handle = window.requestAnimationFrame(() => {
            forget();
            this._runDeferred(fn);
        });
        forget = this.__colibri__.addCleanup(() => window.cancelAnimationFrame(handle));
        return handle;
    }

    /**
     * Debounces a function and makes sure it is cancelled upon destroy.
     */
    debounced(fn, delay, options) {
        fn = this.__colibri__.protectSyncAfterAsync(this, "debounced", fn);
        const debouncedFn = debounce(
            async (...args) => {
                await fn.apply(this, args);
                if (this.isReady && !this.isDestroyed) {
                    this.updateContent();
                }
            },
            delay,
            options,
        );
        this.registerCleanup(() => {
            debouncedFn.cancel();
        });
        return asDeferredHandler(this, debouncedFn);
    }

    /**
     * Throttles a function for animation and makes sure it is cancelled upon
     * destroy.
     */
    throttled(fn) {
        fn = this.__colibri__.protectSyncAfterAsync(this, "throttled", fn);
        const throttledFn = throttleForAnimation(async (...args) => {
            await fn.apply(this, args);
            if (this.isReady && !this.isDestroyed) {
                this.updateContent();
            }
        });
        this.registerCleanup(() => {
            throttledFn.cancel();
        });
        return asDeferredHandler(this, throttledFn);
    }

    /**
     * Makes sure the function is not started again before it is completed.
     * If required, add a loading animation on button if the execution takes
     * more than 400ms.
     */
    locked(fn, useLoadingAnimation = false) {
        fn = this.__colibri__.protectSyncAfterAsync(this, "locked", fn);
        if (useLoadingAnimation) {
            return makeButtonHandler(fn);
        }
        return makeAsyncHandler(fn);
    }

    /**
     * Adds a listener to the target. Whenever the listener is executed, the
     * dynamic content will be applied. Also, the listener will automatically be
     * cleaned up when the interaction is destroyed.
     * Returns a function to remove the listener(s).
     *
     * @param {EventTarget|EventTarget[]|NodeList} target one or more element(s) / bus
     * @param {string} event
     * @param {Function} fn
     * @param {Object} [options]
     * @returns {Function} removes the listeners
     */
    addListener(target, event, fn, options) {
        return this.__colibri__.addListener(toEventTargets(target), event, fn, options)
            .remove;
    }

    /**
     * Inserts and activate an element at a specific location (default position:
     * "beforeend").
     * The inserted element will be removed when the interaction is destroyed.
     *
     * @param { HTMLElement } el
     * @param { HTMLElement } [locationEl] the target
     * @param { "afterbegin" | "afterend" | "beforebegin" | "beforeend" } [position]
     * @param { boolean } [removeOnClean]
     */
    insert(el, locationEl = this.el, position = "beforeend", removeOnClean = true) {
        this._attach(el, locationEl, position, removeOnClean);
        this.services["public.interactions"].startInteractions(el);
        this.__colibri__.refreshNodes();
    }

    /**
     * Puts an element in the page and arranges for its removal, without
     * activating it. Split out of `insert` so that a caller inserting several
     * elements can activate them in one pass: a scan costs one `querySelectorAll`
     * per *registered interaction class*, a fixed price paid per scan and not
     * per node, so `renderAt` used to multiply it by the number of elements it
     * rendered.
     *
     * @param { HTMLElement } el
     * @param { HTMLElement } locationEl
     * @param { "afterbegin" | "afterend" | "beforebegin" | "beforeend" } position
     * @param { boolean } removeOnClean
     * @returns { void }
     */
    _attach(el, locationEl, position, removeOnClean) {
        const interactions = this.services["public.interactions"];
        locationEl.insertAdjacentElement(position, el);
        if (removeOnClean) {
            // the subtree gets activated, so removing it has to deactivate it
            // as well: detaching the nodes on its own left their interactions
            // registered and running on an element no longer in the document.
            // The removal is in a `finally` because `stopInteractions` reports
            // a failing nested `destroy()` by throwing: one such interaction
            // anywhere in the inserted markup stranded the whole subtree in
            // the page, outliving the interaction that put it there.
            this.registerCleanup(() => {
                try {
                    interactions.stopInteractions(el);
                } finally {
                    el.remove();
                }
            });
        }
    }

    /**
     * Removes the children of an element.
     * The children will be inserted back when the interaction is destroyed.
     *
     * They come back inert: their interactions are stopped here and are not
     * started again, because a teardown step cannot start interactions. A stop
     * pass iterates over a snapshot of the service's list and filters that list
     * afterwards, so anything registered while it runs survives it — the
     * restored subtree would be left running on a page meant to be stopped. The
     * next full scan (the website builder does one on every mode change) picks
     * the markup back up.
     *
     * @param { HTMLElement } el
     * @param { boolean } [insertBackOnClean]
     */
    removeChildren(el, insertBackOnClean = true) {
        // snapshot first: `el.children` is live and stopping an interaction can
        // detach nodes, which would make the iteration skip siblings and leave
        // their interactions running on elements no longer in the document
        for (const child of [...el.children]) {
            this.services["public.interactions"].stopInteractions(
                /** @type {HTMLElement} */ (child),
            );
        }
        const children = [...el.childNodes];
        el.replaceChildren();
        if (insertBackOnClean) {
            this.registerCleanup(() => el.replaceChildren(...children));
        }
    }

    /**
     * Renders, inserts and activates an element at a specific location.
     * The inserted element will be removed when the interaction is destroyed.
     *
     * @param { string } template
     * @param { Object } renderContext
     * @param { HTMLElement } [locationEl] the target
     * @param { "afterbegin" | "afterend" | "beforebegin" | "beforeend" } [position]
     * @param { Function } [callback] called with rendered elements before insertion
     * @param { boolean } [removeOnClean]
     * @returns { HTMLElement[] } rendered elements
     */
    renderAt(
        template,
        renderContext,
        locationEl,
        position = "beforeend",
        callback,
        removeOnClean = true,
    ) {
        const fragment = renderToFragment(template, renderContext);
        const result = /** @type {HTMLElement[]} */ ([...fragment.children]);
        const els = [...result];
        callback?.(els);
        if (["afterend", "afterbegin"].includes(position)) {
            els.reverse();
        }
        for (const el of els) {
            this._attach(
                /** @type {HTMLElement} */ (el),
                locationEl ?? this.el,
                position,
                removeOnClean,
            );
        }
        // one scan for the whole batch, not one per element
        this.services["public.interactions"].startInteractions(els);
        this.__colibri__.refreshNodes();
        return result;
    }

    /**
     * Registers a function that will be executed when the interaction is
     * destroyed. It is sometimes useful, so we can explicitly add the cleanup
     * at the location where the side effect is created.
     *
     * @param {Function} fn
     * @returns {Function} forgets the cleanup without running it
     */
    registerCleanup(fn) {
        return this.__colibri__.addCleanup(fn.bind(this));
    }

    /**
     * Mounts an Owl component.
     *
     * @param {HTMLElement} el
     * @param {import("@odoo/owl").ComponentConstructor} C
     * @param {Object|null} [props]
     * @returns {Function} destroy function for early removal
     */
    mountComponent(el, C, props = null, position = "beforeend") {
        return this.__colibri__.mountComponent(el, C, props, position);
    }
}
