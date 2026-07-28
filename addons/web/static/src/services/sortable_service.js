// @ts-check
/** @odoo-module native */

/**
 * @module @web/services/sortable_service - Service for creating sortable drag-and-drop outside OWL component lifecycle
 *
 * Used by modules that need drag-and-drop outside OWL lifecycle (e.g. website_slides).
 * Most OWL components use the `useSortable()` hook from `@web/core/utils/dnd/sortable_owl` directly.
 */

import { reactive } from "@odoo/owl";
import { registry } from "@web/core/registry";
import { useSortable } from "@web/core/utils/dnd/sortable";
import { throttleForAnimation } from "@web/core/utils/timing";

/**
 * @typedef {Record<string, any> & {
 *  ref?: {el: HTMLElement} | ReturnType<typeof import("@odoo/owl").useRef>;
 *  sortableId?: string | symbol;
 * }} SortableServiceHookParams
 */

const DEFAULT_SORTABLE_ID = Symbol.for("defaultSortable");

/**
 * Service for creating drag-and-drop sortable behaviors on DOM elements
 * outside the OWL component lifecycle. Manages element binding to avoid
 * duplicate setups and provides explicit enable/cleanup control.
 */
export const sortableService = {
    /** @returns {{ create: (hookParams: SortableServiceHookParams) => { enable: () => { cleanup: () => void } } }} */
    start() {
        /**
         * Map to avoid to setup/enable twice or more time the same element
         * @type {Map<Element, Object>}
         */
        const boundElements = new Map();
        return {
            /**
             * @param {SortableServiceHookParams} hookParams
             */
            create: (hookParams) => {
                if (!hookParams?.ref) {
                    // Reaching `.el` on an absent ref throws a bare TypeError
                    // that hides which of the two contract violations happened.
                    throw new Error(
                        "sortable service: create() requires a `ref` in hookParams",
                    );
                }
                const element = hookParams.ref.el;
                if (!element) {
                    // The ref is not mounted yet. Keying `boundElements` by
                    // `undefined` collapses every such call onto ONE entry, so
                    // the second unmounted sortable is handed the first one's
                    // cleanup and never sets itself up.
                    throw new Error(
                        "sortable service: create() requires a mounted ref " +
                            "(hookParams.ref.el is not set)",
                    );
                }
                const sortableId = hookParams.sortableId ?? DEFAULT_SORTABLE_ID;
                if (boundElements.has(element)) {
                    const boundElement = boundElements.get(element);
                    if (/** @type {any} */ (sortableId) in boundElement) {
                        return {
                            enable() {
                                return {
                                    cleanup:
                                        boundElements.get(element)?.[sortableId] ??
                                        (() => {}),
                                };
                            },
                        };
                    }
                }
                /**
                 * @type {Map<Function, function(): any[]>}
                 */
                const setupFunctions = new Map();
                /**
                 * @type {Array<Function>}
                 */
                const cleanupFunctions = [];

                const cleanup = () => {
                    const boundElement = boundElements.get(element);
                    if (
                        boundElement &&
                        /** @type {any} */ (sortableId) in boundElement
                    ) {
                        delete (/** @type {any} */ (boundElement)[sortableId]);
                        if (Reflect.ownKeys(boundElement).length === 0) {
                            boundElements.delete(element);
                        }
                    }
                    // Drain rather than iterate: `cleanup` is handed to callers
                    // and is also reachable through `boundElements`, so calling
                    // it twice used to run every teardown callback twice.
                    cleanupFunctions.splice(0).forEach((fn) => fn());
                };

                const setupHooks = {
                    wrapState: reactive,
                    throttle: throttleForAnimation,
                    addListener: (
                        /** @type {EventTarget} */ el,
                        /** @type {string} */ type,
                        /** @type {EventListenerOrEventListenerObject} */ listener,
                    ) => {
                        el.addEventListener(type, listener);
                        cleanupFunctions.push(() =>
                            el.removeEventListener(type, listener),
                        );
                    },
                    setup: (
                        /** @type {Function} */ setupFn,
                        /** @type {() => any[]} */ dependenciesFn,
                    ) => setupFunctions.set(setupFn, dependenciesFn),
                    teardown: (/** @type {Function} */ fn) => cleanupFunctions.push(fn),
                };

                useSortable(/** @type {any} */ ({ setupHooks, ...hookParams }));

                const boundElement = boundElements.get(element);
                if (boundElement) {
                    /** @type {any} */ (boundElement)[sortableId] = cleanup;
                } else {
                    boundElements.set(
                        element,
                        /** @type {any} */ ({ [sortableId]: cleanup }),
                    );
                }

                let enabled = false;
                return {
                    enable() {
                        if (!enabled) {
                            enabled = true;
                            setupFunctions.forEach((dependenciesFn, setupFn) =>
                                setupFn(...dependenciesFn()),
                            );
                        }
                        return {
                            cleanup,
                        };
                    },
                };
            },
        };
    },
};

registry.category("services").add("sortable", sortableService);
