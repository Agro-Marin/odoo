// @ts-check
/** @odoo-module native */

/** @module @web/public/interaction */

import { renderToFragment } from "@web/core/utils/render";
import { debounce, throttleForAnimation } from "@web/core/utils/timing";

import { INITIAL_VALUE, SKIP_IMPLICIT_UPDATE, toEventTargets } from "./colibri.js";
import { makeAsyncHandler, makeButtonHandler } from "./minimal_dom.js";

/**
 * @param {Interaction} interaction
 * @param {((...args: any[]) => any) & { cancel: () => void }} fn
 * @returns {((...args: any[]) => symbol) & { cancel: () => void }}
 */
function asDeferredHandler(interaction, fn) {
    /** @param {any[]} args */
    const handler = (...args) => {
        Promise.resolve(fn(...args)).catch((error) =>
            interaction.services["public.interactions"].reportError(error),
        );
        return SKIP_IMPLICIT_UPDATE;
    };
    Object.defineProperty(handler, "name", { value: fn.name, configurable: true });
    handler.cancel = fn.cancel;
    return handler;
}

export class Interaction {
    /**
     * @type {string}
     */
    static selector = "";

    /**
     * @type {string}
     */
    static selectorHas = "";

    /**
     * @type {string}
     */
    static selectorNotHas = "";

    static INITIAL_VALUE = INITIAL_VALUE;

    /**
     * @type {Object.<string, Function>}
     */
    dynamicSelectors = {
        _root: () => this.el,
        _body: () => this.el.ownerDocument.body,
        _window: () => this.el.ownerDocument.defaultView || window,
        _document: () => this.el.ownerDocument,
    };

    /**
     * @type {Record<string, Record<string, any>>}
     */
    dynamicContent = {};

    /**
     * @param {HTMLElement} el
     * @param {import("@web/env").OdooEnv} env
     * @param {import("./colibri").Colibri} metadata
     */
    constructor(el, env, metadata) {
        this.__colibri__ = metadata;
        this.el = el;
        this.env = env;
        /** @type {import("services").ServiceFactories} */
        this.services = env.services;
    }

    get isReady() {
        return this.__colibri__.isReady;
    }

    get isDestroyed() {
        return this.__colibri__.isDestroyed;
    }

    setup() {}

    async willStart() {}

    /** @returns {void | Promise<void>} */
    start() {}

    destroy() {}

    updateContent() {
        this.__colibri__.updateContent();
    }

    waitFor(promise = Promise.resolve()) {
        const prom = new Promise((resolve, reject) => {
            const updateAfterCaller = () => {
                if (this.isReady && !this.isDestroyed) {
                    try {
                        this.updateContent();
                    } catch (error) {
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
     * @param {Function} fn
     * @return {Function}
     */
    protectSyncAfterAsync(fn) {
        return this.__colibri__.protectSyncAfterAsync(
            this,
            "protectSyncAfterAsync",
            fn,
        );
    }

    /**
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
     * @param {Function} fn
     * @param {number} delay
     * @returns {number}
     */
    waitForTimeout(fn, delay) {
        fn = this.__colibri__.protectSyncAfterAsync(this, "waitForTimeout", fn);
        /** @type {() => void} */
        let forget;
        const timer = setTimeout(() => {
            forget();
            this._runDeferred(fn);
        }, delay);
        forget = this.__colibri__.addCleanup(() => clearTimeout(timer));
        return timer;
    }

    /**
     * @param {Function} fn
     * @returns {number}
     */
    waitForAnimationFrame(fn) {
        fn = this.__colibri__.protectSyncAfterAsync(this, "waitForAnimationFrame", fn);
        /** @type {() => void} */
        let forget;
        const handle = window.requestAnimationFrame(() => {
            forget();
            this._runDeferred(fn);
        });
        forget = this.__colibri__.addCleanup(() => window.cancelAnimationFrame(handle));
        return handle;
    }

    /**
     * @param {Function} fn
     * @param {number} delay
     * @param {Object} [options]
     * @returns {((...args: any[]) => symbol) & { cancel: () => void }}
     */
    debounced(fn, delay, options) {
        fn = this.__colibri__.protectSyncAfterAsync(this, "debounced", fn);
        const debouncedFn = debounce(
            /** @param {any[]} args */
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
     * @param {Function} fn
     * @returns {((...args: any[]) => symbol) & { cancel: () => void }}
     */
    throttled(fn) {
        fn = this.__colibri__.protectSyncAfterAsync(this, "throttled", fn);
        const throttledFn = throttleForAnimation(
            /** @param {any[]} args */
            async (...args) => {
                await fn.apply(this, args);
                if (this.isReady && !this.isDestroyed) {
                    this.updateContent();
                }
            },
        );
        this.registerCleanup(() => {
            throttledFn.cancel();
        });
        return asDeferredHandler(this, throttledFn);
    }

    /**
     * @param {(...args: any[]) => any} fn
     * @param {boolean} [useLoadingAnimation]
     * @returns {(ev: Event) => any}
     */
    locked(fn, useLoadingAnimation = false) {
        const protectedFn = /** @type {(...args: any[]) => any} */ (
            this.__colibri__.protectSyncAfterAsync(this, "locked", fn)
        );
        if (useLoadingAnimation) {
            return makeButtonHandler(protectedFn);
        }
        return makeAsyncHandler(protectedFn);
    }

    /**
     * @param {EventTarget|EventTarget[]|NodeList} target
     * @param {string} event
     * @param {Function} fn
     * @param {Object} [options]
     * @returns {Function}
     */
    addListener(target, event, fn, options) {
        return this.__colibri__.addListener(toEventTargets(target), event, fn, options)
            .remove;
    }

    /**
     * @param { HTMLElement } el
     * @param { HTMLElement } [locationEl]
     * @param { "afterbegin" | "afterend" | "beforebegin" | "beforeend" } [position]
     * @param { boolean } [removeOnClean]
     */
    insert(el, locationEl = this.el, position = "beforeend", removeOnClean = true) {
        this._attach(el, locationEl, position, removeOnClean);
        this.services["public.interactions"].startInteractions(el);
        this.__colibri__.refreshNodes();
    }

    /**
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
     * @param { HTMLElement } el
     * @param { boolean } [insertBackOnClean]
     */
    removeChildren(el, insertBackOnClean = true) {
        const errors = [];
        for (const child of [...el.children]) {
            try {
                this.services["public.interactions"].stopInteractions(
                    /** @type {HTMLElement} */ (child),
                );
            } catch (error) {
                errors.push(error);
            }
        }
        const children = [...el.childNodes];
        el.replaceChildren();
        if (insertBackOnClean) {
            this.registerCleanup(() => el.replaceChildren(...children));
        }
        for (const error of errors) {
            this.services["public.interactions"].reportError(error);
        }
    }

    /**
     * @param { string } template
     * @param { Object } [renderContext]
     * @param { HTMLElement } [locationEl]
     * @param { "afterbegin" | "afterend" | "beforebegin" | "beforeend" } [position]
     * @param { Function } [callback]
     * @param { boolean } [removeOnClean]
     * @returns { HTMLElement[] }
     */
    renderAt(
        template,
        renderContext = {},
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
        this.services["public.interactions"].startInteractions(els);
        this.__colibri__.refreshNodes();
        return result;
    }

    /**
     * @param {Function} fn
     * @returns {Function}
     */
    registerCleanup(fn) {
        return this.__colibri__.addCleanup(fn.bind(this));
    }

    /**
     * @param {HTMLElement} el
     * @param {import("@odoo/owl").ComponentConstructor} C
     * @param {Object|null} [props]
     * @param {InsertPosition} [position]
     * @returns {Function}
     */
    mountComponent(el, C, props = null, position = "beforeend") {
        return this.__colibri__.mountComponent(el, C, props, position);
    }
}
