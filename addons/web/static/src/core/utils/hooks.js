// @ts-check
/** @odoo-module native */

/** @module @web/core/utils/hooks */

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
 * @typedef {{ readonly el: HTMLElement | null; }} Ref
 */

/**
 * @param {Object} [params]
 * @param {string} [params.refName]
 * @param {boolean} [params.selectAll]
 * @param {boolean} [params.mobile]
 * @returns {Ref}
 */
export function useAutofocus({ refName, selectAll, mobile } = {}) {
    const ref = useRef(refName || "autofocus");
    const uiService = useService("ui");

    if (!mobile && hasTouch()) {
        return ref;
    }
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

/**
 * ``EventBus.trigger`` always dispatches a ``CustomEvent`` carrying its payload
 * in ``detail``, so the callback is typed against that rather than the bare
 * ``EventListener`` an ``EventTarget`` would take.
 *
 * @param {import("@odoo/owl").EventBus} bus
 * @param {string} eventName
 * @param {(ev: CustomEvent<any>) => void} callback
 * @returns {void}
 */
export function useBus(bus, eventName, callback) {
    const component = useComponent();
    useEffect(
        () => {
            const listener = /** @type {EventListener} */ (callback.bind(component));
            bus.addEventListener(eventName, listener);
            return () => bus.removeEventListener(eventName, listener);
        },
        () => [],
    );
}

export const useServiceProtectMethodHandling = {
    /** @returns {Promise<never>} */
    fn() {
        return this.original();
    },
    /** @returns {Promise<never>} */
    mocked() {
        return new Promise(() => {});
    },
    /** @returns {Promise<never>} */
    original() {
        return Promise.reject(new Error("Component is destroyed"));
    },
};

/**
 * Both settle paths are withheld once the owner is destroyed, not just the
 * resolve one. Letting rejections through meant a request started by a
 * component the user has since navigated away from still reached
 * ``error_service``'s ``unhandledrejection`` listener and opened a crash dialog
 * for a view that is no longer on screen. A destroyed component can act on a
 * failure no more than it can act on a result, so the error is logged for
 * developers and withheld from the UI.
 *
 * ``resolve`` is called per invocation rather than closed over once: the
 * wrapper is installed as an own property that shadows the service, so
 * capturing the function at mount time would pin the component to that
 * snapshot and silently ignore any later replacement of the method
 * (``patch``, ``mockService``, a module patching the service in place).
 *
 * @param {import("@odoo/owl").Component} component
 * @param {() => Function} resolve
 * @returns {Function}
 */
function _protectMethod(component, resolve) {
    return function (/** @type {any[]} */ ...args) {
        if (status(component) === "destroyed") {
            return useServiceProtectMethodHandling.fn();
        }

        const prom = Promise.resolve(resolve().call(this, ...args));
        const protectedProm = prom.then(
            (result) =>
                status(component) === "destroyed" ? new Promise(() => {}) : result,
            (error) => {
                if (status(component) !== "destroyed") {
                    throw error;
                }
                console.warn(
                    "Discarded a service call that failed after its component was destroyed:",
                    error,
                );
                return new Promise(() => {});
            },
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
    const observed =
        toRaw(service) !== service
            ? /** @type {any} */ (useState(/** @type {any} */ (service)))
            : service;
    if (SERVICES_METADATA[serviceName]) {
        if (service instanceof Function) {
            return /** @type {import("services").ServiceFactories[K]} */ (
                _protectMethod(component, () => services[serviceName])
            );
        }
        const methods = SERVICES_METADATA[serviceName] ?? [];
        const result = Object.create(observed);
        for (const method of methods) {
            result[method] = _protectMethod(component, () => observed[method]);
        }
        return result;
    }
    return observed;
}

/**
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
 * @see useForwardRefToParent
 * @returns {ForwardRef}
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
 * @see useChildRef
 * @param {string} refName
 * @returns {Ref}
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
 * @returns {(...args: any[]) => () => void}
 */
export function useOwnedDialogs() {
    const dialogService = useService("dialog");
    const closers = new Set();
    onWillUnmount(() => {
        closers.forEach((close) => close());
        closers.clear();
    });
    const addDialog = (
        /** @type {any} */ dialogClass,
        /** @type {any} */ props,
        /** @type {any} */ options = {},
    ) => {
        const originalOnClose = options.onClose;
        const originalClose = /** @type {any} */ (dialogService).add(
            dialogClass,
            props,
            {
                ...options,
                onClose: (/** @type {any[]} */ ...onCloseArgs) => {
                    closers.delete(wrappedClose);
                    return originalOnClose?.(...onCloseArgs);
                },
            },
        );
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
 * @param {Ref} ref
 * @param {...any} listener
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
