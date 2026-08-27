// @ts-check
/** @odoo-module native */

/**
 * @typedef Position
 * @property {number} x
 * @property {number} y
 */

/**
 * @param {Node} node
 * @returns {Window}
 */
export function viewOf(node) {
    return node.ownerDocument?.defaultView ?? window;
}

/**
 * @param {Node | DocumentOrShadowRoot | null} [node]
 * @returns {Element | null}
 */
export function getActiveElement(node) {
    const root = /** @type {Node} */ (node)?.getRootNode?.() ?? node;
    const scope = /** @type {DocumentOrShadowRoot} */ (
        root && "activeElement" in root
            ? root
            : /** @type {Node} */ (node)?.ownerDocument
    );
    return scope?.activeElement ?? null;
}

/**
 * @param {Node | DocumentOrShadowRoot | null} [node]
 * @returns {Element | null}
 */
export function getDeepActiveElement(node) {
    let active = getActiveElement(node);
    for (;;) {
        const inShadow = active?.shadowRoot?.activeElement;
        if (inShadow) {
            active = inShadow;
            continue;
        }
        /** @type {Element | null} */
        let inFrame;
        try {
            inFrame =
                /** @type {HTMLIFrameElement} */ (active)?.contentDocument
                    ?.activeElement ?? null;
        } catch {
            inFrame = null;
        }
        if (!inFrame || inFrame === active) {
            return active;
        }
        active = inFrame;
    }
}

/**
 * @param {HTMLElement} host
 * @param {ShadowRootInit} [init]
 * @returns {ShadowRoot}
 */
export function attachShadowRoot(host, init = { mode: "open" }) {
    host.setAttribute(SHADOW_HOST_ATTRIBUTE, "");
    return host.shadowRoot ?? host.attachShadow(init);
}

const SHADOW_HOST_ATTRIBUTE = "data-shadow-host";
const SHADOW_HOST_SELECTOR = `[${SHADOW_HOST_ATTRIBUTE}]`;

/**
 * @param {Iterable<HTMLElement>} elements
 * @param {Position} targetPos
 * @returns {HTMLElement | null}
 */
export function closest(elements, targetPos) {
    let closestEl = null;
    let closestDistance = Infinity;
    for (const el of elements) {
        const rect = el.getBoundingClientRect();
        const distance = getQuadrance(rect, targetPos);
        if (!closestEl || distance < closestDistance) {
            closestEl = el;
            closestDistance = distance;
        }
    }
    return closestEl;
}

/**
 * @param {any} el
 * @returns {boolean}
 */
export function isVisible(el) {
    if (!el) {
        return false;
    }
    if (el.nodeType === Node.DOCUMENT_NODE || el.window === el) {
        return true;
    }
    let _isVisible = false;
    if ("offsetWidth" in el && "offsetHeight" in el) {
        _isVisible = el.offsetWidth > 0 && el.offsetHeight > 0;
    } else if ("getBoundingClientRect" in el) {
        const rect = el.getBoundingClientRect();
        _isVisible = rect.width > 0 && rect.height > 0;
    }
    if (!_isVisible && viewOf(el).getComputedStyle(el).display === "contents") {
        for (const child of el.children) {
            if (isVisible(child)) {
                return true;
            }
        }
    }
    return _isVisible;
}

/**
 * @param {DOMRect} rect
 * @param {Position} pos
 * @returns {number}
 */
function getQuadrance(rect, pos) {
    let q = 0;
    if (pos.x < rect.x) {
        q += (rect.x - pos.x) ** 2;
    } else if (rect.x + rect.width < pos.x) {
        q += (pos.x - (rect.x + rect.width)) ** 2;
    }
    if (pos.y < rect.y) {
        q += (rect.y - pos.y) ** 2;
    } else if (rect.y + rect.height < pos.y) {
        q += (pos.y - (rect.y + rect.height)) ** 2;
    }
    return q;
}

/**
 * @param {Element} container
 * @param {string} selector
 * @returns {HTMLElement[]}
 */
export function getVisibleElements(container, selector) {
    const visibleElements = [];
    /** @type {NodeListOf<HTMLElement>} */
    const elements = container.querySelectorAll(selector);
    for (const el of elements) {
        if (isVisible(el)) {
            visibleElements.push(el);
        }
    }
    return visibleElements;
}

/**
 * @param {Iterable<HTMLElement>} elements
 * @param {Partial<DOMRect>} targetRect
 * @returns {HTMLElement[]}
 */
export function touching(elements, targetRect) {
    const r1 = { x: 0, y: 0, width: 0, height: 0, ...targetRect };
    return [...elements].filter((el) => {
        const r2 = el.getBoundingClientRect();
        return (
            r2.x + r2.width >= r1.x &&
            r2.x <= r1.x + r1.width &&
            r2.y + r2.height >= r1.y &&
            r2.y <= r1.y + r1.height
        );
    });
}

const FOCUSABLE_SELECTORS = [
    "[tabindex]",
    "a[href]",
    "area[href]",
    "button",
    "frame",
    "iframe",
    "input",
    "object",
    "select",
    "textarea",
    "details > summary:nth-child(1)",
].map((sel) => `${sel}:not(:disabled)`);
const TABABLE_SELECTORS = FOCUSABLE_SELECTORS.map(
    (sel) => `${sel}:not([tabindex="-1"])`,
);
const FOCUSABLE_SELECTOR = FOCUSABLE_SELECTORS.join(",");
const TABABLE_SELECTOR = TABABLE_SELECTORS.join(",");
const TABABLE_OR_HOST_SELECTOR = `${TABABLE_SELECTOR},${SHADOW_HOST_SELECTOR}`;

/**
 * @param {HTMLElement} el
 */
export function isFocusable(el) {
    return el.matches(FOCUSABLE_SELECTOR) && isVisible(el) && !el.closest("[inert]");
}

/**
 * @param {HTMLElement | DocumentFragment} [container=document.body]
 * @returns {HTMLElement[]}
 */
export function getTabableElements(container = document.body) {
    /** @type {HTMLElement[]} */
    const elements = [];
    collectTabable(container, elements);
    const byTabIndex = /** @type {Record<number, HTMLElement[]>} */ (
        Object.groupBy(elements, (el) => el.tabIndex)
    );

    const withTabIndexZero = byTabIndex[0] || [];
    delete byTabIndex[0];
    return [...Object.values(byTabIndex).flat(), ...withTabIndexZero];
}

/**
 * @param {HTMLElement | DocumentFragment} root
 * @param {HTMLElement[]} out
 */
function collectTabable(root, out) {
    if (!root.querySelector(SHADOW_HOST_SELECTOR)) {
        for (const el of /** @type {NodeListOf<HTMLElement>} */ (
            root.querySelectorAll(TABABLE_SELECTOR)
        )) {
            if (el.tabIndex >= 0 && isVisible(el) && !el.closest("[inert]")) {
                out.push(el);
            }
        }
        return;
    }
    for (const el of /** @type {NodeListOf<HTMLElement>} */ (
        root.querySelectorAll(TABABLE_OR_HOST_SELECTOR)
    )) {
        const inert = el.closest("[inert]");
        if (
            el.tabIndex >= 0 &&
            !inert &&
            isVisible(el) &&
            el.matches(TABABLE_SELECTOR)
        ) {
            out.push(el);
        }
        if (el.shadowRoot && !inert) {
            collectTabable(/** @type {any} */ (el.shadowRoot), out);
        }
    }
}

/**
 * @param {HTMLElement} [container]
 * @returns {HTMLElement | null}
 */
export function getNextTabableElement(container = document.body) {
    const tabableElements = getTabableElements(container);
    const index = tabableElements.indexOf(
        /** @type {any} */ (getActiveElement(container)),
    );
    return index === -1 ? tabableElements[0] : tabableElements[index + 1] || null;
}

/**
 * @param {HTMLElement} [container]
 * @returns {HTMLElement | undefined | null}
 */
export function getPreviousTabableElement(container = document.body) {
    const tabableElements = getTabableElements(container);
    const index = tabableElements.indexOf(
        /** @type {any} */ (getActiveElement(container)),
    );
    return index === -1 ? tabableElements.at(-1) : tabableElements[index - 1] || null;
}

const LOADING_EFFECT_CLASSES = ["o_btn_loading", "disabled", "pe-none"];

/**
 * @param {HTMLButtonElement} btnEl
 * @return {function}
 */
export function addLoadingEffect(btnEl) {
    const hadClass = LOADING_EFFECT_CLASSES.map((cl) => btnEl.classList.contains(cl));
    const isDisableable = "disabled" in btnEl;
    const wasDisabled = btnEl.disabled;
    btnEl.classList.add(...LOADING_EFFECT_CLASSES);
    if (isDisableable) {
        btnEl.disabled = true;
    }
    const loaderEl = btnEl.ownerDocument.createElement("span");
    loaderEl.classList.add("fa", "fa-circle-o-notch", "fa-spin", "me-2");
    btnEl.prepend(loaderEl);
    return () => {
        for (const [index, cl] of LOADING_EFFECT_CLASSES.entries()) {
            btnEl.classList.toggle(cl, hadClass[index]);
        }
        if (isDisableable) {
            btnEl.disabled = wasDisabled;
        }
        loaderEl.remove();
    };
}
