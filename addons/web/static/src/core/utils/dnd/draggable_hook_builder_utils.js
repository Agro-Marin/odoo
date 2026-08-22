// @ts-check
/** @odoo-module native */

import { closestScrollableX, closestScrollableY } from "@web/core/utils/dom/scrolling";

const DRAGGABLE_CLASS = "o_draggable";
export const DRAGGED_CLASS = "o_dragged";

export const DEFAULT_ACCEPTED_PARAMS = {
    allowDisconnected: [Boolean],
    enable: [Boolean, Function],
    preventDrag: [Function],
    ref: [Object],
    elements: [String],
    handle: [String, Function],
    ignore: [String, Function],
    cursor: [String],
    edgeScrolling: [Object, Function],
    delay: [Number],
    tolerance: [Number],
    touchDelay: [Number],
    iframeWindow: [Object, Function],
};
export const DEFAULT_DEFAULT_PARAMS = {
    allowDisconnected: false,
    elements: `.${DRAGGABLE_CLASS}`,
    enable: true,
    preventDrag: () => false,
    edgeScrolling: {
        speed: 10,
        threshold: 30,
    },
    delay: 0,
    tolerance: 10,
    touchDelay: 300,
};
export const LEFT_CLICK = 0;
export const MANDATORY_PARAMS = ["ref"];
export const WHITE_LISTED_KEYS = ["Alt", "Control", "Meta", "Shift"];

/**
 * @param {string} str
 * @returns {string}
 */
function camelToKebab(str) {
    return str.replace(/([a-z])([A-Z])/g, "$1-$2").toLowerCase();
}

/**
 * @template T
 * @param {T | (() => T)} valueOrFn
 * @returns {T}
 */
export function getReturnValue(valueOrFn) {
    if (typeof valueOrFn === "function") {
        return /** @type {() => T} */ (valueOrFn)();
    }
    return valueOrFn;
}

/**
 * @param {HTMLElement} el
 * @returns {(HTMLElement | null)[]}
 */
export function getScrollParents(el) {
    return [closestScrollableX(el), closestScrollableY(el)];
}

/**
 * @param {string} val
 * @returns {number}
 */
function pixelValueToNumber(val) {
    return Number(val.endsWith("px") ? val.slice(0, -2) : val);
}

/**
 * @param {Event} ev
 * @param {{ stop?: boolean }} params
 */
export function safePrevent(ev, { stop } = {}) {
    if (ev.cancelable) {
        ev.preventDefault();
        if (stop) {
            ev.stopPropagation();
        }
    }
}

/**
 * @template T
 * @param {T | (() => T)} value
 * @returns {() => T}
 */
export function toFunction(value) {
    return typeof value === "function" ? /** @type {() => T} */ (value) : () => value;
}

/**
 * @type {Record<string, WeakSet<HTMLElement>>}
 */
const elCache = {};

/**
 * @param {HTMLElement} el
 * @param {string} attribute
 * @returns {(() => void) | undefined}
 */
function saveAttribute(el, attribute) {
    const restoreAttribute = () => {
        cache.delete(el);
        if (originalValue !== null) {
            el.setAttribute(attribute, originalValue);
        } else {
            el.removeAttribute(attribute);
        }
    };

    if (!(attribute in elCache)) {
        elCache[attribute] = new WeakSet();
    }
    const cache = elCache[attribute];

    if (cache.has(el)) {
        return;
    }

    cache.add(el);
    const originalValue = el.getAttribute(attribute);

    return restoreAttribute;
}

/**
 * @param {() => any} [defaultCleanupFn]
 * @returns {{ add: (fn?: () => any) => void, cleanup: () => void }}
 */
export function makeCleanupManager(defaultCleanupFn) {
    /**
     * @param {() => any} [cleanupFn]
     */
    const add = (cleanupFn) =>
        typeof cleanupFn === "function" && cleanups.push(cleanupFn);

    const cleanup = () => {
        while (cleanups.length) {
            try {
                cleanups.pop()?.();
            } catch (error) {
                console.error(error);
            }
        }
        add(defaultCleanupFn);
    };

    /** @type {(() => void)[]} */
    const cleanups = [];

    add(defaultCleanupFn);

    return { add, cleanup };
}

/**
 * @param {ReturnType<typeof makeCleanupManager>} cleanup
 */
export function makeDOMHelpers(cleanup) {
    /**
     * @param {HTMLElement | null} el
     * @param {...string} classNames
     */
    const addClass = (el, ...classNames) => {
        if (!el || !classNames.length) {
            return;
        }
        cleanup.add(() => el.classList.remove(...classNames));
        el.classList.add(...classNames);
    };

    /**
     * @param {EventTarget} el
     * @param {string} event
     * @param {(...args: any[]) => any} callback
     * @param {AddEventListenerOptions & { noAddedStyle?: boolean }} [options]
     */
    const addListener = (el, event, callback, options = {}) => {
        if (!el || !event || !callback) {
            return;
        }
        const { noAddedStyle, ...listenerOptions } = options;
        el.addEventListener(event, callback, listenerOptions);
        if (!noAddedStyle && /mouse|pointer|touch/.test(event)) {
            addStyle(/** @type {HTMLElement} */ (el), {
                pointerEvents: "auto",
            });
        }
        cleanup.add(() => el.removeEventListener(event, callback, listenerOptions));
    };

    /**
     * @param {HTMLElement} el
     * @param {Record<string, string | number>} style
     */
    const addStyle = (el, style) => {
        if (!el || !style || !Object.keys(style).length) {
            return;
        }
        cleanup.add(saveAttribute(el, "style"));
        for (const key of Object.keys(style)) {
            const [value, priority] = String(style[key]).split(/\s*!\s*/);
            el.style.setProperty(camelToKebab(key), value, priority);
        }
    };

    /**
     * @param {HTMLElement} el
     * @param {Object} [options={}]
     * @param {boolean} [options.adjust=false]
     * @returns {DOMRect}
     */
    const getRect = (el, options = {}) => {
        if (!el) {
            return /** @type {DOMRect} */ ({});
        }
        const rect = el.getBoundingClientRect();

        rect.height = el.offsetHeight;

        if (options.adjust) {
            const style = getComputedStyle(el);
            const [pl, pr, pt, pb] = [
                "padding-left",
                "padding-right",
                "padding-top",
                "padding-bottom",
            ].map((prop) => pixelValueToNumber(style.getPropertyValue(prop)));

            rect.x += pl;
            rect.y += pt;
            rect.width -= pl + pr;
            rect.height -= pt + pb;
        }
        return rect;
    };

    /**
     * @param {HTMLElement} el
     * @param {string} attribute
     */
    const removeAttribute = (el, attribute) => {
        if (!el || !attribute) {
            return;
        }
        cleanup.add(saveAttribute(el, attribute));
        el.removeAttribute(attribute);
    };

    /**
     * @param {HTMLElement} el
     * @param {...string} classNames
     */
    const removeClass = (el, ...classNames) => {
        if (!el || !classNames.length) {
            return;
        }
        cleanup.add(saveAttribute(el, "class"));
        el.classList.remove(...classNames);
    };

    /**
     * @param {HTMLElement} el
     * @param {...string} properties
     */
    const removeStyle = (el, ...properties) => {
        if (!el || !properties.length) {
            return;
        }
        cleanup.add(saveAttribute(el, "style"));
        for (const key of properties) {
            el.style.removeProperty(camelToKebab(key));
        }
    };

    /**
     * @param {HTMLElement} el
     * @param {string} attribute
     * @param {any} value
     */
    const setAttribute = (el, attribute, value) => {
        if (!el || !attribute) {
            return;
        }
        cleanup.add(saveAttribute(el, attribute));
        el.setAttribute(attribute, String(value));
    };

    return {
        addClass,
        addListener,
        addStyle,
        getRect,
        removeAttribute,
        removeClass,
        removeStyle,
        setAttribute,
    };
}
