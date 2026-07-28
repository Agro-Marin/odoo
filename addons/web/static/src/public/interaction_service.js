// @ts-check
/** @odoo-module native */

/** @module @web/public/interaction_service - Core service that discovers, mounts, and manages Interaction instances on DOM elements */

import { App, Component } from "@odoo/owl";
import { appTranslateFn } from "@web/core/l10n/translation";
import { registry } from "@web/core/registry";
import { getTemplate } from "@web/core/templates";

import { Colibri } from "./colibri.js";
import { Interaction } from "./interaction.js";
import { PairSet } from "./utils.js";

registry
    .category("public.interactions")
    .addValidation(
        (entry) =>
            entry?.prototype instanceof Interaction ||
            entry?.prototype instanceof Component,
    );

/**
 * Two kinds of interactions: `Interaction` subclasses (owl-free, declarative
 * DOM manipulation + event handlers) and Owl `Component` subclasses (full
 * Owl access, for more complex UI needs).
 */

export class InteractionService {
    /**
     * @param {HTMLElement} el root element to monitor for interactions
     * @param {import("@web/env").OdooEnv} env
     */
    constructor(el, env) {
        this.Interactions = [];
        this.el = el;
        this.activeInteractions = new PairSet();
        this.env = env;
        this.interactions = [];
        this.roots = [];
        this.owlApp = null;
        this.proms = [];
        /** @type {WeakSet<Object>} */
        this.reportedErrors = new WeakSet();
        // set by website_edit_service, which also patches shouldStop() to read
        // isRefreshing; declared here so the contract is visible from the class
        this.editMode = false;
        this.isRefreshing = false;
    }

    /**
     * Registers interaction classes and starts them on the target element.
     *
     * @param {Array<typeof import("@web/public/interaction").Interaction>} Interactions
     * @param {HTMLElement} [target]
     * @returns {void}
     */
    activate(Interactions, target) {
        this.Interactions = Interactions;
        const startProm = this.env.isReady.then(() => this.startInteractions(target));
        this._trackProm(startProm);
    }

    /**
     * Tracks a pending promise for `isReady`. A fulfilled one is dropped at
     * once; a rejected one is held until an `isReady` read has surfaced it,
     * then dropped there — keeping it forever made every later read reject
     * long after the failing scan was history, and grew `this.proms` without
     * bound. The rejection handler here also keeps the derived promise from
     * reporting an unhandled rejection of its own.
     *
     * @param {Promise<any>} prom
     * @returns {void}
     */
    _trackProm(prom) {
        this.proms.push(prom);
        prom.then(
            () => this._forgetProm(prom),
            (error) => {
                // a scan is tracked both on its own and through the promise
                // `activate` derives from it, so one failure reaches this
                // handler twice; identity keeps it a single report
                if (error instanceof Object) {
                    if (this.reportedErrors.has(error)) {
                        return;
                    }
                    this.reportedErrors.add(error);
                }
                this.reportError(error);
            },
        );
    }

    /**
     * @param {Promise<any>} prom
     * @returns {void}
     */
    _forgetProm(prom) {
        const index = this.proms.indexOf(prom);
        if (index !== -1) {
            this.proms.splice(index, 1);
        }
    }

    /**
     * Single channel for surfacing interaction failures. Every async path in
     * this framework — an event handler, a deferred callback, a scan started by
     * insert() or by a t-out re-scan — catches its own errors rather than let
     * them escape from a promise nobody holds, and funnels them here.
     *
     * Catching is not handling. What turns a failure into something the visitor
     * can act on is `@web/services/error_service`, and its only entry point is
     * the global "unhandledrejection" event: `rpcErrorHandler` bails unless it
     * is given an `UncaughtPromiseError`, which nothing but that listener
     * builds. An RPCError reported by console alone is therefore never matched
     * against the `error_notifications` / `error_dialogs` registries — the very
     * registries the sibling error_notifications.js fills for public pages — so
     * a website form that failed server-side told the visitor nothing at all.
     *
     * Putting the failure back on that channel is what upstream's handler
     * wrapper did by simply not catching. The error is re-raised unwrapped, so
     * its stack still points at the interaction and the handlers still classify
     * it by its own type.
     *
     * @param {unknown} error
     * @returns {void}
     */
    reportError(error) {
        Promise.reject(error);
    }

    /**
     * Prepares a mountable OWL component root inside the given element.
     *
     * @param {HTMLElement} el
     * @param {import("@odoo/owl").ComponentConstructor} C
     * @param {Record<string, any>} [props]
     * @param {InsertPosition} [position]
     * @returns {{ C: import("@odoo/owl").ComponentConstructor, root: any, el: HTMLElement, hostEl: HTMLElement, mount: () => Promise<any>, destroy: () => void }}
     */
    prepareRoot(el, C, props, position = "beforeend") {
        if (!this.owlApp) {
            const appConfig = {
                name: "Odoo Website",
                getTemplate,
                env: this.env,
                dev: this.env.debug,
                translateFn: appTranslateFn,
                warnIfNoStaticProps: this.env.debug,
                translatableAttributes: ["data-tooltip"],
            };
            this.owlApp = new App(null, /** @type {any} */ (appConfig));
        }
        const root = /** @type {any} */ (this.owlApp).createRoot(C, {
            props,
            env: this.env,
        });
        const rootEl = document.createElement("owl-root");
        rootEl.setAttribute("contenteditable", "false");
        rootEl.dataset.oeProtected = "true";
        rootEl.style.display = "contents";
        el.insertAdjacentElement(position, rootEl);
        let isDestroyed = false;
        return {
            C,
            root,
            el: rootEl,
            hostEl: el,
            mount: () => root.mount(rootEl),
            destroy: () => {
                if (isDestroyed) {
                    return;
                }
                isDestroyed = true;
                root.destroy();
                rootEl.remove();
            },
        };
    }

    /**
     * @param {HTMLElement} el
     * @param {import("@odoo/owl").ComponentConstructor} C
     * @returns {Promise<void>}
     */
    async _mountComponent(el, C) {
        const root = this.prepareRoot(el, C);
        this.roots.push(root);
        try {
            return await root.mount();
        } catch (error) {
            // a half-mounted root and its <owl-root> host must not survive:
            // they would linger in the DOM and be destroyed a second time by
            // the next stopInteractions()
            this.roots = this.roots.filter((r) => r !== root);
            root.destroy();
            throw error;
        }
    }

    /**
     * Starts all registered interactions on elements matching their selectors
     * inside `target`, which may be one root or several.
     *
     * The loop is over the interaction classes, not the roots: each class costs
     * a `querySelectorAll` whatever the subtree's size, so that is the price of
     * a scan, and several roots scanned together pay it once. `renderAt` used
     * to insert its elements one at a time and pay it per element.
     *
     * @param {HTMLElement | HTMLElement[]} [target]
     * @returns {Promise<void>}
     */
    startInteractions(target = this.el) {
        const roots = (Array.isArray(target) ? target : [target]).filter(
            (el) => el.isConnected,
        );
        if (!roots.length) {
            return Promise.resolve();
        }
        const proms = /** @type {Array<Promise<void>>} */ ([]);
        for (const I of this.Interactions) {
            if (I.selector === "") {
                proms.push(
                    Promise.reject(
                        new Error(
                            `The selector should be defined as a static property on the class ${I.name}, not on the instance`,
                        ),
                    ),
                );
                continue;
            }
            if (I.dynamicContent) {
                proms.push(
                    Promise.reject(
                        new Error(
                            `The dynamic content object should be defined on the instance, not on the class (${I.name})`,
                        ),
                    ),
                );
                continue;
            }
            let targets;
            try {
                targets = [];
                for (const root of roots) {
                    if (root.matches(I.selector)) {
                        targets.push(root);
                    }
                    targets.push(...root.querySelectorAll(I.selector));
                }
                if (I.selectorHas) {
                    targets = targets.filter((el) => !!el.querySelector(I.selectorHas));
                }
                if (I.selectorNotHas) {
                    targets = targets.filter(
                        (el) => !el.querySelector(I.selectorNotHas),
                    );
                }
            } catch {
                const selectorHasError = I.selectorHas
                    ? ` or selectorHas: '${I.selectorHas}'`
                    : "";
                const selectorNotHasError = I.selectorNotHas
                    ? ` or selectorNotHas: '${I.selectorNotHas}'`
                    : "";
                const error = new Error(
                    `Could not start interaction ${I.name} (invalid selector: '${I.selector}'${selectorHasError}${selectorNotHasError})`,
                );
                proms.push(Promise.reject(error));
                continue;
            }
            for (const _el of targets) {
                this._startInteraction(_el, I, proms);
            }
        }
        // allSettled and not all: `all` settles on the first rejection and
        // discards every other one, so a scan in which several interactions
        // crashed only ever reported one of them
        const prom = Promise.allSettled(proms).then((results) => {
            const errors = results
                .filter((result) => result.status === "rejected")
                .map((result) => result.reason);
            if (errors.length === 1) {
                throw errors[0];
            }
            if (errors.length) {
                throw new AggregateError(errors, "Could not start some interactions");
            }
        });
        this._trackProm(prom);
        return prom;
    }

    /**
     * @param {HTMLElement} el
     * @param {typeof import("@web/public/interaction").Interaction} I
     * @param {Array<Promise<any>>} proms
     * @returns {void}
     */
    _startInteraction(el, I, proms) {
        if (this.activeInteractions.has(el, I)) {
            return;
        }
        this.activeInteractions.add(el, I);
        if (I.prototype instanceof Interaction) {
            try {
                const interaction = new Colibri(this, I, el);
                this.interactions.push(interaction);
                proms.push(
                    interaction.start().catch((e) => {
                        this.interactions = this.interactions.filter(
                            (i) => i !== interaction,
                        );
                        this.activeInteractions.delete(el, I);
                        throw e;
                    }),
                );
            } catch (e) {
                this.activeInteractions.delete(el, I);
                // reported through the scan like any other start failure: sent
                // to `_trackProm` directly, it stayed invisible to whoever
                // awaited that very scan's promise
                proms.push(Promise.reject(e));
            }
        } else {
            proms.push(
                this._mountComponent(
                    el,
                    /** @type {import("@odoo/owl").ComponentConstructor} */ (
                        /** @type {unknown} */ (I)
                    ),
                ).catch((e) => {
                    this.activeInteractions.delete(el, I);
                    throw e;
                }),
            );
        }
    }

    /**
     * @param {HTMLElement} el
     * @param {import("@web/public/colibri").Colibri} interaction
     * @returns {boolean}
     */
    shouldStop(el, interaction) {
        const { selectorNotHas, selectorHas } = /** @type {any} */ (
            interaction.interaction.constructor
        );
        if (!interaction.el) {
            return true;
        }
        return (
            el.contains(interaction.el) ||
            (selectorHas && !interaction.el.querySelector(selectorHas)) ||
            (selectorNotHas && !!interaction.el.querySelector(selectorNotHas))
        );
    }

    /**
     * Destroys all active interactions started on elements inside `el`.
     *
     * @param {HTMLElement} [el]
     * @returns {void}
     */
    stopInteractions(el = this.el) {
        const errors = [];
        const stoppedInteractions = new Set();
        for (const interaction of this.interactions.toReversed()) {
            if (this.shouldStop(el, interaction)) {
                stoppedInteractions.add(interaction);
                try {
                    interaction.destroy();
                } catch (error) {
                    errors.push([interaction.interaction.constructor.name, error]);
                }
                this.activeInteractions.delete(
                    interaction.el,
                    interaction.interaction.constructor,
                );
            }
        }
        this.interactions = this.interactions.filter(
            (interaction) => !stoppedInteractions.has(interaction),
        );
        const stoppedRoots = new Set();
        for (const root of this.roots.toReversed()) {
            if (el.contains(root.el)) {
                stoppedRoots.add(root);
                root.destroy();
                this.activeInteractions.delete(root.hostEl ?? root.el, root.C);
            }
        }
        this.roots = this.roots.filter((root) => !stoppedRoots.has(root));
        if (errors.length) {
            throw new AggregateError(
                errors.map(
                    ([interaction, error]) =>
                        new Error(`Could not destroy interaction ${interaction}`, {
                            cause: error,
                        }),
                ),
                "Could not destroy some interactions",
            );
        }
    }

    /**
     * @returns { Promise } settles once all current interactions have started;
     * does not track future ones. Rejects if any of them failed, and forgets
     * those failures afterwards so a later read reflects the scans it awaited
     * rather than every crash the page ever had.
     */
    get isReady() {
        const proms = this.proms.slice();
        return Promise.allSettled(proms).then((results) => {
            // a scan is tracked both on its own and through the promise
            // `activate` derives from it, so one failure surfaces on two
            // promises; identity keeps it a single error
            const errors = new Set();
            for (const [index, result] of results.entries()) {
                if (result.status === "rejected") {
                    errors.add(result.reason);
                    this._forgetProm(proms[index]);
                }
            }
            if (errors.size === 1) {
                throw [...errors][0];
            }
            if (errors.size) {
                throw new AggregateError(
                    [...errors],
                    "Could not start some interactions",
                );
            }
        });
    }
}

export const publicInteractionService = {
    dependencies: ["localization"],
    async start(env) {
        const el = /** @type {HTMLElement} */ (
            document.getElementById("wrapwrap") || document.body
        );
        const Interactions = /** @type {(typeof Interaction)[]} */ (
            registry.category("public.interactions").getAll()
        );
        const service = new InteractionService(el, env);
        service.activate(Interactions);
        return service;
    },
};

registry
    .category("services")
    .add("public.interactions", /** @type {any} */ (publicInteractionService));
