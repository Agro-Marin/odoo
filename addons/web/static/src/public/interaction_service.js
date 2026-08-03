// @ts-check
/** @odoo-module native */

/** @module @web/public/interaction_service */

import { App, Component } from "@odoo/owl";
import { reportUncaught } from "@web/core/errors/error_utils";
import { registry } from "@web/core/registry";
import { getTemplate } from "@web/core/templates";
import { appTranslateFn } from "@web/core/translation";

import { Colibri } from "./colibri.js";
import { Interaction } from "./interaction.js";
import { PairSet } from "./utils.js";

/**
 * @typedef {Object} PreparedRoot
 * @property {import("@odoo/owl").ComponentConstructor} C
 * @property {any} root
 * @property {HTMLElement} el
 * @property {HTMLElement} hostEl
 * @property {() => Promise<any>} mount
 * @property {() => void} destroy
 */

registry
    .category("public.interactions")
    .addValidation(
        (entry) =>
            entry?.prototype instanceof Interaction ||
            entry?.prototype instanceof Component,
    );

export class InteractionService {
    /**
     * @param {HTMLElement} el
     * @param {import("@web/env").OdooEnv} env
     */
    constructor(el, env) {
        /** @type {Array<typeof Interaction>} */
        this.Interactions = [];
        this.el = el;
        /** @type {PairSet<HTMLElement, Function>} */
        this.activeInteractions = new PairSet();
        this.env = env;
        /** @type {Colibri[]} */
        this.interactions = [];
        /** @type {PreparedRoot[]} */
        this.roots = [];
        this.owlApp = null;
        /** @type {Promise<any>[]} */
        this.proms = [];
        /** @type {WeakSet<Object>} */
        this.reportedErrors = new WeakSet();
        this.editMode = false;
        this.isRefreshing = false;
    }

    /**
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
     * @param {Promise<any>} prom
     * @returns {void}
     */
    _trackProm(prom) {
        this.proms.push(prom);
        prom.then(
            () => this._forgetProm(prom),
            (error) => {
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
     * @param {PreparedRoot} root
     * @returns {void}
     */
    forgetRoot(root) {
        const index = this.roots.indexOf(root);
        if (index !== -1) {
            this.roots.splice(index, 1);
        }
    }

    /**
     * @param {unknown} error
     * @returns {void}
     */
    reportError(error) {
        reportUncaught(error);
    }

    /**
     * @param {HTMLElement} el
     * @param {import("@odoo/owl").ComponentConstructor} C
     * @param {Record<string, any>} [props]
     * @param {InsertPosition} [position]
     * @returns {PreparedRoot}
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
            this.owlApp = new App(
                /** @type {any} */ (null),
                /** @type {any} */ (appConfig),
            );
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
                try {
                    root.destroy();
                } finally {
                    rootEl.remove();
                }
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
            this.forgetRoot(root);
            try {
                root.destroy();
            } catch (cleanupError) {
                this.reportError(cleanupError);
            }
            throw error;
        }
    }

    /**
     * @param {HTMLElement} el
     * @returns {boolean}
     */
    coversWholeRoot(el) {
        return el === this.el || el.contains(this.el);
    }

    /**
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
            if (/** @type {any} */ (I).dynamicContent) {
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
        // A blanket stop stops everything this service owns, including whatever
        // `el` cannot reach: an element already detached, and an element living
        // in another document altogether. The latter is `isConnected` -- it is
        // connected to ITS document -- so an `isConnected` test alone left it
        // running forever, and with it any listener it bound to the real window
        // through `_window`'s `defaultView || window` fallback.
        if (this.coversWholeRoot(el) && !el.contains(interaction.el)) {
            return true;
        }
        return (
            el.contains(interaction.el) ||
            (selectorHas && !interaction.el.querySelector(selectorHas)) ||
            (selectorNotHas && !!interaction.el.querySelector(selectorNotHas))
        );
    }

    /**
     * @param {(interaction: import("@web/public/colibri").Colibri) => boolean} selectsInteraction
     * @param {(root: any) => boolean} selectsRoot
     * @returns {void}
     */
    stopMatching(selectsInteraction, selectsRoot) {
        const errors = [];
        const stoppedInteractions = new Set();
        for (const interaction of this.interactions.toReversed()) {
            if (selectsInteraction(interaction)) {
                stoppedInteractions.add(interaction);
                try {
                    interaction.destroy();
                } catch (error) {
                    errors.push([
                        `interaction ${interaction.interaction.constructor.name}`,
                        error,
                    ]);
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
            if (selectsRoot(root)) {
                stoppedRoots.add(root);
                try {
                    root.destroy();
                } catch (error) {
                    errors.push([`component ${root.C?.name || "root"}`, error]);
                }
                this.activeInteractions.delete(root.hostEl ?? root.el, root.C);
            }
        }
        this.roots = this.roots.filter((root) => !stoppedRoots.has(root));
        if (errors.length) {
            throw new AggregateError(
                errors.map(
                    ([what, error]) =>
                        new Error(`Could not destroy ${what}`, { cause: error }),
                ),
                "Could not destroy some interactions",
            );
        }
    }

    /**
     * @param {HTMLElement} [el]
     * @returns {void}
     */
    stopInteractions(el = this.el) {
        const coversWholeRoot = this.coversWholeRoot(el);
        this.stopMatching(
            (interaction) => this.shouldStop(el, interaction),
            (root) =>
                coversWholeRoot ||
                el.contains(root.el) ||
                // A detached <owl-root> cannot be placed by containment, so
                // the host answers for it: anything that rewrites the host's
                // content detaches it, and matching on it alone left the root
                // -- and the live component under it -- behind for good. Only
                // when it is detached, though: a root still in the page sits
                // where it was mounted, and that may be outside `el`.
                (!root.el.isConnected && el.contains(root.hostEl)),
        );
    }

    /**
     * @param {string} name
     * @returns {void}
     */
    stopInteractionsByName(name) {
        const I = registry.category("public.interactions").get(name);
        this.stopMatching(
            (interaction) => interaction.interaction.constructor === I,
            (root) => root.C === I,
        );
    }

    /**
     * @returns {void}
     */
    stopDisconnectedInteractions() {
        this.stopMatching(
            (interaction) => !interaction.el?.isConnected,
            (root) =>
                !root.el.isConnected || !!(root.hostEl && !root.hostEl.isConnected),
        );
    }

    /**
     * @returns {Promise<void>}
     */
    get isReady() {
        const proms = this.proms.slice();
        return Promise.allSettled(proms).then((results) => {
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
    /** @param {import("@web/env").OdooEnv} env */
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
