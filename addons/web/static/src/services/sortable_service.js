// @ts-check
/** @odoo-module native */

/**
 * @module @web/services/sortable_service
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

export const sortableService = {
    /**
     * @returns {{ create: (hookParams: SortableServiceHookParams) => { enable: () => { cleanup: () => void } } }}
     */
    start() {
        /** @type {WeakMap<Element, Record<string | symbol, () => void>>} */
        const boundElements = new WeakMap();
        return {
            /**
             * @param {SortableServiceHookParams} hookParams
             */
            create: (hookParams) => {
                if (!hookParams?.ref) {
                    throw new Error(
                        "sortable service: create() requires a `ref` in hookParams",
                    );
                }
                const element = hookParams.ref.el;
                if (!element) {
                    throw new Error(
                        "sortable service: create() requires a mounted ref " +
                            "(hookParams.ref.el is not set)",
                    );
                }
                const sortableId = hookParams.sortableId ?? DEFAULT_SORTABLE_ID;
                if (boundElements.has(element)) {
                    const boundElement = boundElements.get(element);
                    if (boundElement && sortableId in boundElement) {
                        return {
                            enable() {
                                return {
                                    cleanup: boundElement[sortableId] ?? (() => {}),
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
                    if (boundElement && sortableId in boundElement) {
                        delete boundElement[sortableId];
                        if (Reflect.ownKeys(boundElement).length === 0) {
                            boundElements.delete(element);
                        }
                    }
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
                    boundElement[sortableId] = cleanup;
                } else {
                    boundElements.set(element, { [sortableId]: cleanup });
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
