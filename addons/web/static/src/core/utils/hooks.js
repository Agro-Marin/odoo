// @ts-check
/** @odoo-module native */

import {
    onPatched,
    onWillUnmount,
    status,
    toRaw,
    useComponent,
    useEffect,
    useRef,
    useState,
} from "@odoo/owl";
import { hasTouch, isMobileOS } from "@web/core/browser/feature_detection";
import { getActiveElement } from "@web/core/utils/dom/ui";

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

/**
 * @type {WeakMap<string[], Set<PropertyKey>>}
 */
const guardedMethodSets = new WeakMap();

/**
 * @param {string[]} methods
 * @returns {Set<PropertyKey>}
 */
function guardedMethodSet(methods) {
    let set = guardedMethodSets.get(methods);
    if (!set) {
        set = new Set(methods);
        guardedMethodSets.set(methods, set);
    }
    return set;
}

/**
 * @param {import("@odoo/owl").Component} component
 * @param {any} observed
 * @param {string[]} methods
 * @returns {any}
 */
function makeGuardedView(component, observed, methods) {
    const methodSet = guardedMethodSet(methods);
    /** @type {Map<PropertyKey, Function>} */
    const guarded = new Map();
    return new Proxy(observed, {
        get(target, property) {
            if (methodSet.has(property)) {
                let fn = guarded.get(property);
                if (!fn) {
                    fn = _protectMethod(component, () => observed[property]);
                    guarded.set(property, fn);
                }
                return fn;
            }
            const value = Reflect.get(target, property, target);
            if (
                value !== null &&
                typeof value === "object" &&
                Object.getPrototypeOf(value) === target
            ) {
                return makeGuardedView(component, value, methods);
            }
            return value;
        },
    });
}

/** @type {Record<string, string[]>} */
export const SERVICES_METADATA = {};

/**
 * @template {keyof import("services").ServiceFactories} K
 * @param {K} serviceName
 * @returns {import("services").ServiceFactories[K]}
 */
export function useService(serviceName) {
    const service = _useService(serviceName, false);
    return /** @type {import("services").ServiceFactories[K]} */ (service);
}

/**
 * @template {keyof import("services").ServiceFactories} K
 * @param {K} serviceName
 * @returns {import("services").ServiceFactories[K] | null}
 */
export function useOptionalService(serviceName) {
    return /** @type {any} */ (_useService(serviceName, true));
}

/**
 * @param {string} serviceName
 * @param {boolean} optional
 * @returns {any}
 */
function _useService(serviceName, optional) {
    const component = useComponent();
    const { services } = component.env;
    if (!(serviceName in services)) {
        if (optional) {
            return null;
        }
        throw new Error(`Service ${serviceName} is not available`);
    }
    const service = services[serviceName];
    const observed =
        toRaw(service) !== service
            ? /** @type {any} */ (useState(/** @type {any} */ (service)))
            : service;
    if (SERVICES_METADATA[serviceName]) {
        if (service instanceof Function) {
            return _protectMethod(component, () => services[serviceName]);
        }
        const methods = SERVICES_METADATA[serviceName] ?? [];
        return makeGuardedView(component, observed, methods);
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
            getActiveElement(/** @type {Node} */ (ev.target)) === ev.target;
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
 * @typedef {((ref: Ref) => void) & { readonly el: HTMLElement | null }} ForwardRef
 * @property {HTMLElement | undefined} el
 */

/**
 * @param {() => HTMLInputElement | null | undefined} getElement
 * @param {() => any} getValue
 * @param {{ property?: "value" | "checked" }} [options]
 * @returns {() => boolean}
 */
export function useSyncedInputProperty(
    getElement,
    getValue,
    { property = "value" } = {},
) {
    const sync = () => {
        const element = getElement();
        const value = getValue();
        if (!element || value === undefined || element[property] === value) {
            return false;
        }
        if (property === "checked") {
            element.checked = Boolean(value);
        } else {
            element.value = value;
        }
        return true;
    };
    onPatched(sync);
    return sync;
}

/**
 * @returns {ForwardRef}
 */
export function useChildRef() {
    let defined = false;
    /** @type {Ref} */
    let value;
    return /** @type {ForwardRef} */ (
        function ref(/** @type {Ref} */ v) {
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
        }
    );
}
/**
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
