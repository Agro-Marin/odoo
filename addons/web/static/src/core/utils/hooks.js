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
 * ``this`` is forwarded from the call site on purpose — a caller may rebind a
 * protected method, and the protected view must otherwise be indistinguishable
 * from the service. Keeping that transparency is why the view is a Proxy rather
 * than ``Object.create(service)``; see ``useService``.
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

/**
 * Build the destroy-guarding view a component sees for a class-shaped service:
 * a Proxy whose `async:` methods are swapped for guarded ones and whose every
 * other member reads straight through.
 *
 * A Proxy, not `Object.create(observed)`. The view exists only to swap the
 * `async:` methods for guarded ones; it must be transparent in every other
 * respect, and a prototype-chain view is not. `this` inside a guarded method is
 * the view (deliberately -- see `_protectMethod`), so with `Object.create` a
 * `this.x = …` created an OWN property on the view and the service never saw the
 * write. Reads still resolved down the chain, so nothing failed loudly: each
 * component simply kept its own private copy from the moment it first wrote.
 * `file_upload` minted duplicate upload ids that way -- every component started
 * again from the service's stale `nextId`, and `uploads[id]` is shared, so one
 * upload's record overwrote another's. A closure-shaped service was immune
 * because its state lived in the closure rather than on `this`; returning an
 * instance from `start()` is exactly what moves it, so this had to be fixed here
 * rather than in each converted service.
 *
 * A getter modifier (the `orm.silent` / `orm.dedup` shape) returns an object
 * created off the service via `Object.create(this)`. Read through this Proxy the
 * getter runs with the raw service as `this` (the receiver below), so the
 * derived object's async methods would resolve on the unguarded prototype and
 * escape the destroy protection -- `orm.silent.read(...)` resolving into a view
 * the user had already left. Such a derived view -- recognised by its prototype
 * being this very target -- is therefore re-wrapped so its methods are guarded
 * too. (Method modifiers like `orm.cache()` need no help: they are invoked with
 * the Proxy as `this`, so their result already chains through it.)
 *
 * @param {import("@odoo/owl").Component} component
 * @param {any} observed
 * @param {string[]} methods
 * @returns {any}
 */
function makeGuardedView(component, observed, methods) {
    const guarded = new Map();
    for (const method of methods) {
        guarded.set(
            method,
            _protectMethod(component, () => observed[method]),
        );
    }
    return new Proxy(observed, {
        get(target, property) {
            if (guarded.has(property)) {
                return guarded.get(property);
            }
            // Receiver is the target, so a getter on the service reads the
            // service rather than re-entering this trap.
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
