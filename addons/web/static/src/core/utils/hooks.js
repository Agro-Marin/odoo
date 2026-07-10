// @ts-check
/** @odoo-module native */

/** @module @web/core/utils/hooks - OWL component hooks: useService, useBus, useAutofocus, useOwnedDialogs, useForwardRefToParent */

import {
    onWillUnmount,
    status,
    toRaw,
    useComponent,
    useEffect,
    useRef,
    useState,
} from "@odoo/owl";
import { hasTouch, isMobileOS } from "@web/core/browser/feature_detection";

/**
 * This file contains various custom hooks.
 * Their inner working is rather simple:
 * Each custom hook simply hooks itself to any number of owl lifecycle hooks.
 * You can then use them just like an owl hook in any Component
 * e.g.:
 * import { useBus } from "@web/core/utils/hooks";
 * ...
 * setup() {
 *    ...
 *    useBus(someBus, someEvent, callback)
 *    ...
 * }
 */

/**
 * @typedef {{ readonly el: HTMLElement | null; }} Ref
 */

// -----------------------------------------------------------------------------
// useAutofocus
// -----------------------------------------------------------------------------

/**
 * Focus an element referenced by a t-ref="autofocus" in the active component
 * as soon as it appears in the DOM and if it was not displayed before.
 * If it is an input/textarea, set the selection at the end.
 * @param {Object} [params]
 * @param {string} [params.refName] override the ref name "autofocus"
 * @param {boolean} [params.selectAll] if true, will select the entire text value.
 * @param {boolean} [params.mobile] if true, will force autofocus on touch devices.
 * @returns {Ref} the element reference
 */
export function useAutofocus({ refName, selectAll, mobile } = {}) {
    const ref = useRef(refName || "autofocus");
    const uiService = useService("ui");

    // Prevent autofocus on touch devices to avoid the virtual keyboard from popping up unexpectedly
    if (!mobile && hasTouch()) {
        return ref;
    }
    // LEGACY
    if (!mobile && isMobileOS()) {
        return ref;
    }
    function isFocusable(/** @type {HTMLElement | null} */ el) {
        if (!el) {
            return false;
        }
        if (!uiService.activeElement || uiService.activeElement.contains(el)) {
            return true;
        }
        const rootNode = el.getRootNode();
        return (
            rootNode instanceof ShadowRoot &&
            uiService.activeElement.contains(rootNode.host)
        );
    }
    // LEGACY
    useEffect(
        (el) => {
            if (isFocusable(el)) {
                el.focus();
                if (
                    ["INPUT", "TEXTAREA"].includes(el.tagName) &&
                    /** @type {HTMLInputElement} */ (el).type !== "number"
                ) {
                    const input = /** @type {HTMLInputElement} */ (el);
                    input.selectionEnd = input.value.length;
                    input.selectionStart = selectAll ? 0 : input.value.length;
                }
            }
        },
        () => [ref.el],
    );
    return ref;
}

// -----------------------------------------------------------------------------
// useBus
// -----------------------------------------------------------------------------

/**
 * Ensures a bus event listener is attached and cleared the proper way.
 *
 * @param {import("@odoo/owl").EventBus} bus
 * @param {string} eventName
 * @param {EventListener} callback
 * @returns {void}
 */
export function useBus(bus, eventName, callback) {
    const component = useComponent();
    useEffect(
        () => {
            const listener = callback.bind(component);
            bus.addEventListener(eventName, listener);
            return () => bus.removeEventListener(eventName, listener);
        },
        () => [],
    );
}

/**
 * Patchable object for controlling protected method behavior in tests.
 * In production, returns a rejected promise when the component is destroyed.
 * In tests, can be mocked to return an unresolved promise to prevent crashes.
 */
export const useServiceProtectMethodHandling = {
    /** @returns {Promise<never>} */
    fn() {
        return this.original();
    },
    /** @returns {Promise<never>} */
    mocked() {
        // Keep them unresolved so that no crash in test due to triggered RPCs by services
        return new Promise(() => {});
    },
    /** @returns {Promise<never>} */
    original() {
        return Promise.reject(new Error("Component is destroyed"));
    },
};

// -----------------------------------------------------------------------------
// useService
// -----------------------------------------------------------------------------
/**
 * Wrap a service method so that it returns a pending promise when the
 * owning component is destroyed, preventing post-teardown side effects.
 *
 * @param {import("@odoo/owl").Component} component
 * @param {Function} fn
 * @returns {Function}
 */
function _protectMethod(component, fn) {
    return function (/** @type {any[]} */ ...args) {
        if (status(component) === "destroyed") {
            return useServiceProtectMethodHandling.fn();
        }

        const prom = Promise.resolve(fn.call(this, ...args));
        const protectedProm = prom.then((result) =>
            status(component) === "destroyed" ? new Promise(() => {}) : result,
        );
        return Object.assign(protectedProm, {
            abort: /** @type {any} */ (prom).abort,
            cancel: /** @type {any} */ (prom).cancel,
        });
    };
}

/** @type {Record<string, string[]>} */
export const SERVICES_METADATA = {};

/**
 * Import a service into a component
 *
 * @template {keyof import("services").ServiceFactories} K
 * @param {K} serviceName
 * @returns {import("services").ServiceFactories[K]}
 */
export function useService(serviceName) {
    const component = useComponent();
    const { services } = component.env;
    if (!(serviceName in services)) {
        throw new Error(`Service ${serviceName} is not available`);
    }
    const service = services[serviceName];
    if (SERVICES_METADATA[serviceName]) {
        if (service instanceof Function) {
            return /** @type {import("services").ServiceFactories[K]} */ (
                _protectMethod(component, service)
            );
        } else {
            const methods = SERVICES_METADATA[serviceName] ?? [];
            const result = Object.create(service);
            for (const method of methods) {
                result[method] = _protectMethod(component, service[method]);
            }
            return result;
        }
    }
    if (toRaw(service) !== service) {
        return useState(service);
    }
    return service;
}

// -----------------------------------------------------------------------------
// useSpellCheck
// -----------------------------------------------------------------------------

/**
 * Enables spellcheck only while an element is focused, so the red squiggles
 * don't linger once it loses focus. Opt out via the spellcheck attribute.
 *
 * @param {{ refName?: string }} [params]
 * @returns {void}
 */
export function useSpellCheck({ refName } = {}) {
    const ref = useRef(refName || "spellcheck");
    function toggleSpellcheck(/** @type {Event} */ ev) {
        /** @type {HTMLElement} */ (ev.target).spellcheck =
            document.activeElement === ev.target;
    }
    useEffect(
        (el) => {
            // Collect managed elements per effect run to avoid leaking stale
            // DOM references across re-runs.
            /** @type {Element[]} */
            const elements = [];
            if (el) {
                const inputs =
                    ["INPUT", "TEXTAREA"].includes(el.nodeName) || el.isContentEditable
                        ? [el]
                        : el.querySelectorAll(
                              "input, textarea, [contenteditable=true]",
                          );
                inputs.forEach((/** @type {Element} */ input) => {
                    if (/** @type {HTMLElement} */ (input).spellcheck !== false) {
                        elements.push(input);
                        input.addEventListener("focus", toggleSpellcheck);
                        input.addEventListener("blur", toggleSpellcheck);
                    }
                });
            }
            return () => {
                elements.forEach((input) => {
                    input.removeEventListener("focus", toggleSpellcheck);
                    input.removeEventListener("blur", toggleSpellcheck);
                });
            };
        },
        () => [ref.el],
    );
}

/**
 * @typedef {Function} ForwardRef
 * @property {HTMLElement | undefined} el
 */

/**
 * Use a ref that was forwarded by a child @see useForwardRefToParent
 *
 * @returns {ForwardRef} a ref that can be called to set its value to that of a
 *  child ref, but can otherwise be used as a normal ref object
 */
export function useChildRef() {
    let defined = false;
    /** @type {Ref} */
    let value;
    return function ref(/** @type {Ref} */ v) {
        value = v;
        if (defined) {
            return;
        }
        Object.defineProperty(ref, "el", {
            get() {
                return value.el;
            },
        });
        defined = true;
    };
}
/**
 * Forwards the given refName to the parent by calling the corresponding
 * ForwardRef received as prop. @see useChildRef
 *
 * @param {string} refName name of the ref to forward
 * @returns {Ref} the same ref that is forwarded to the
 *  parent
 */
export function useForwardRefToParent(refName) {
    const component = useComponent();
    const ref = useRef(refName);
    if (component.props[refName]) {
        component.props[refName](ref);
    }
    return ref;
}
/**
 * Use the dialog service while also automatically closing the dialogs opened
 * by the current component when it is unmounted.
 *
 * @returns {(...args: any[]) => () => void}
 */
export function useOwnedDialogs() {
    const dialogService = useService("dialog");
    const closers = new Set();
    onWillUnmount(() => {
        closers.forEach((close) => close());
        closers.clear();
    });
    const addDialog = (/** @type {any[]} */ ...args) => {
        const originalClose = /** @type {any} */ (dialogService).add(...args);
        // Wrap so we can auto-remove from the set when the dialog closes naturally.
        const wrappedClose = () => {
            closers.delete(wrappedClose);
            originalClose();
        };
        closers.add(wrappedClose);
        return wrappedClose;
    };
    return addDialog;
}
/**
 * Manages one or more event listeners on a ref — for hooks that need several.
 * Prefer t-on directly in components; for a single listener, return it from
 * the hook and let the caller attach it with t-on.
 *
 * @param {Ref} ref
 * @param  {...any} listener addEventListener arguments (eventName, handler, options)
 * @returns {void}
 */
export function useRefListener(ref, ...listener) {
    const args = /** @type {[string, EventListenerOrEventListenerObject, ...any[]]} */ (
        listener
    );
    useEffect(
        (el) => {
            el?.addEventListener(...args);
            return () => el?.removeEventListener(...args);
        },
        () => [ref.el],
    );
}
