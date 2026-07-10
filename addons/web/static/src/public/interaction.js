// @ts-check
/** @odoo-module native */

/** @module @web/public/interaction - Base class for public page interactions with selector matching, dynamic content, and service access */

import { renderToFragment } from "@web/core/utils/render";
import { debounce, throttleForAnimation } from "@web/core/utils/timing";

import { INITIAL_VALUE, SKIP_IMPLICIT_UPDATE } from "./colibri.js";
import { makeAsyncHandler, makeButtonHandler } from "./utils.js";
/**
 * Base class for interactions: web-framework integration (env/services), a
 * defined lifecycle, dynamic content, and helpers for common tasks like
 * adding DOM listeners or waiting on async work.
 *
 * Interactions aren't destroyed in the standard workflow (visiting the
 * website), but can be (e.g. switching to "edit" mode) — clean up after
 * yourself.
 */

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
     * querySelector); the directive is then simply ignored.
     *
     * @type {Object.<string, Function>}
     */
    dynamicSelectors = {
        _root: () => this.el,
        _body: () => this.el.ownerDocument.body,
        _window: () => window,
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

    // -------------------------------------------------------------------------
    // lifecycle methods
    // -------------------------------------------------------------------------

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

    // -------------------------------------------------------------------------
    // helpers
    // -------------------------------------------------------------------------

    /**
     * Applies the dynamic content description to the dom synchronously (e.g.
     * dynamic attributes defined with t-att-). Already called after each
     * event handler and by most other helpers, so rarely needed directly.
     */
    updateContent() {
        this.__colibri__.updateContent();
    }

    /**
     * Wraps a promise into a promise that will only be resolved if the instance
     * has not been destroyed, and will also call `updateContent` after the
     * calling code has acted.
     */
    waitFor(promise = Promise.resolve()) {
        const prom = new Promise((resolve, reject) => {
            promise
                .then((result) => {
                    if (!this.isDestroyed) {
                        resolve(result);
                        prom.then(() => {
                            if (this.isReady) {
                                this.updateContent();
                            }
                        });
                    }
                })
                .catch((e) => {
                    reject(e);
                    prom.catch(() => {
                        if (this.isReady && !this.isDestroyed) {
                            this.updateContent();
                        }
                    });
                });
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
     * Wait for a specific timeout, then execute the given function (unless the
     * interaction has been destroyed). The dynamic content is then applied.
     */
    waitForTimeout(fn, delay) {
        fn = this.__colibri__.protectSyncAfterAsync(this, "waitForTimeout", fn);
        return setTimeout(
            () => {
                if (!this.isDestroyed) {
                    fn.call(this);
                    if (this.isReady) {
                        this.updateContent();
                    }
                }
            },
            Number.parseInt(delay, 10),
        );
    }

    /**
     * Wait for a animation frame, then execute the given function (unless the
     * interaction has been destroyed). The dynamic content is then applied.
     */
    waitForAnimationFrame(fn) {
        fn = this.__colibri__.protectSyncAfterAsync(this, "waitForAnimationFrame", fn);
        return window.requestAnimationFrame(() => {
            if (!this.isDestroyed) {
                fn.call(this);
                if (this.isReady) {
                    this.updateContent();
                }
            }
        });
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
        return Object.assign(
            {
                [debouncedFn.name]: (...args) => {
                    debouncedFn(...args);
                    return SKIP_IMPLICIT_UPDATE;
                },
            }[debouncedFn.name],
            {
                cancel: debouncedFn.cancel,
            },
        );
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
        return Object.assign(
            {
                [throttledFn.name]: (...args) => {
                    throttledFn(...args);
                    return SKIP_IMPLICIT_UPDATE;
                },
            }[throttledFn.name],
            {
                cancel: throttledFn.cancel,
            },
        );
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
        /** @type {any[]} */
        let nodes;
        const t = /** @type {any} */ (target);
        if (t.nodeName && ["FORM", "SELECT"].includes(t.nodeName)) {
            nodes = [target];
        } else {
            nodes = t[Symbol.iterator] ? t : [target];
        }
        const [ev, handler, opts] = this.__colibri__.addListener(
            nodes,
            event,
            fn,
            options,
        );
        return () =>
            nodes.forEach((node) => node.removeEventListener(ev, handler, opts));
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
        locationEl.insertAdjacentElement(position, el);
        if (removeOnClean) {
            this.registerCleanup(() => el.remove());
        }
        this.services["public.interactions"].startInteractions(el);
        this.__colibri__.refreshNodes();
    }

    /**
     * Removes the children of an element.
     * The children will be inserted back when the interaction is destroyed.
     *
     * @param { HTMLElement } el
     * @param { boolean } [insertBackOnClean]
     */
    removeChildren(el, insertBackOnClean = true) {
        for (const child of el.children) {
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
        const els = [...fragment.children];
        callback?.(els);
        if (["afterend", "afterbegin"].includes(position)) {
            els.reverse();
        }
        for (const el of els) {
            this.insert(
                /** @type {HTMLElement} */ (el),
                locationEl,
                position,
                removeOnClean,
            );
        }
        return result;
    }

    /**
     * Registers a function that will be executed when the interaction is
     * destroyed. It is sometimes useful, so we can explicitly add the cleanup
     * at the location where the side effect is created.
     *
     * @param {Function} fn
     */
    registerCleanup(fn) {
        this.__colibri__.cleanups.push(fn.bind(this));
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
