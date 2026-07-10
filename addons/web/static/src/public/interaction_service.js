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

// Public-frontend interactions are either subclasses of `Interaction`
// (declarative dom manipulation + event handlers, owl-free) or Owl
// `Component` subclasses. `_startInteraction` dispatches on the prototype
// chain: Interactions are instantiated through `Colibri`, Components are
// mounted through `_mountComponent`. The validator mirrors that dispatch.
registry
    .category("public.interactions")
    .addValidation(
        (entry) =>
            entry?.prototype instanceof Interaction ||
            entry?.prototype instanceof Component,
    );

/**
 * Website Core
 *
 * This service handles the core interactions for the website codebase.
 * It will replace public root, publicroot instance, and all that stuff
 *
 * We have 2 kinds of interactions:
 * - simple interactions (subclasses of Interaction)
 * - components
 *
 * The Interaction class is designed to be a simple class that provides access
 * to the framework (env and services), and a minimalist declarative framework
 * that allows manipulating dom, attaching event handlers and updating it
 * properly. It does not depend on owl.
 *
 * The Component kind of interaction is used for more complicated interface needs.
 * It provides full access to Owl features, but is rendered browser side.
 *
 */

class InteractionService {
    /**
     * @param {HTMLElement} el root element to monitor for interactions
     * @param {import("@web/env").OdooEnv} env
     */
    constructor(el, env) {
        this.Interactions = [];
        this.el = el;
        this.isActive = false;
        // relation el <--> Interaction
        this.activeInteractions = new PairSet();
        this.env = env;
        this.interactions = [];
        this.roots = [];
        this.owlApp = null;
        this.proms = [];
        this.registry = null;
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
     * Tracks a pending promise for `isReady`, and drops it once fulfilled so
     * that `this.proms` does not grow forever. Rejected promises are kept:
     * they are the record of interaction crashes, and `isReady` must reject
     * for them (the no-op rejection handler below only prevents the derived
     * promise from reporting an unhandled rejection of its own).
     *
     * @param {Promise<any>} prom
     * @returns {void}
     */
    _trackProm(prom) {
        this.proms.push(prom);
        prom.then(
            () => {
                const index = this.proms.indexOf(prom);
                if (index !== -1) {
                    this.proms.splice(index, 1);
                }
            },
            () => {},
        );
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
            // ``App`` is typed for ``ComponentConstructor`` as the first arg,
            // but interactions use ``createRoot`` afterwards (each public
            // interaction mounts under its own owl-root); the null root is
            // intentional. Cast keeps the call type-clean.
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
        return {
            C,
            root,
            el: rootEl,
            // The MATCHED host element — activeInteractions is keyed on it
            // (not on the created <owl-root>), so cleanup must use it too.
            hostEl: el,
            mount: () => root.mount(rootEl),
            destroy: () => {
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
        return root.mount();
    }

    /**
     * Starts all registered interactions on elements matching their selectors inside `el`.
     *
     * @param {HTMLElement} [el]
     * @returns {Promise<void>}
     */
    startInteractions(el = this.el) {
        if (!el.isConnected) {
            return Promise.resolve();
        }
        const proms = /** @type {Array<Promise<void>>} */ ([]);
        for (const I of this.Interactions) {
            if (I.selector === "") {
                throw new Error(
                    `The selector should be defined as a static property on the class ${I.name}, not on the instance`,
                );
            }
            if (I.dynamicContent) {
                throw new Error(
                    `The dynamic content object should be defined on the instance, not on the class (${I.name})`,
                );
            }
            let targets;
            try {
                const isMatch = el.matches(I.selector);
                targets = isMatch
                    ? [el, ...el.querySelectorAll(I.selector)]
                    : el.querySelectorAll(I.selector);
                if (I.selectorHas) {
                    targets = [...targets].filter(
                        (el) => !!el.querySelector(I.selectorHas),
                    );
                }
                if (I.selectorNotHas) {
                    targets = [...targets].filter(
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
        if (el === this.el) {
            this.isActive = true;
        }
        const prom = /** @type {Promise<void>} */ (
            /** @type {unknown} */ (Promise.all(proms))
        );
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
                proms.push(interaction.start());
            } catch (e) {
                // Forget the (el, I) pair: a later startInteractions() may
                // retry it, and keeping it would retain `el` forever.
                this.activeInteractions.delete(el, I);
                this._trackProm(Promise.reject(e));
            }
        } else {
            proms.push(
                this._mountComponent(
                    el,
                    /** @type {import("@odoo/owl").ComponentConstructor} */ (
                        /** @type {unknown} */ (I)
                    ),
                ),
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
            el === interaction.el ||
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
        // Destroy in reverse start order, but keep survivors in their
        // original order.
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
            if (el === root.el || el.contains(root.el)) {
                stoppedRoots.add(root);
                root.destroy();
                // The pair was registered with the matched HOST element in
                // _startInteraction — deleting with the created <owl-root>
                // was a silent no-op, permanently blocking a restart of the
                // component interaction on the same element (and retaining
                // the host element in the PairSet).
                this.activeInteractions.delete(root.hostEl ?? root.el, root.C);
            }
        }
        this.roots = this.roots.filter((root) => !stoppedRoots.has(root));
        if (el === this.el) {
            this.isActive = false;
        }
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
     * @returns { Promise } returns a promise that is resolved when all current
     * interactions are started. Note that it does not take into account possible
     * future interactions.
     */
    get isReady() {
        const proms = this.proms.slice();
        return Promise.all(proms);
    }
}

export const publicInteractionService = {
    dependencies: ["localization"],
    async start(env) {
        // fallback if #wrapwrap is not present in the dom
        const el = /** @type {HTMLElement} */ (
            document.querySelector("#wrapwrap") || document.querySelector("body")
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
