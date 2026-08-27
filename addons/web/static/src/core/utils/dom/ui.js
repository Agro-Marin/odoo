// @ts-check
/** @odoo-module native */

/**
 * @typedef Position
 * @property {number} x
 * @property {number} y
 */

/**
 * The window an element actually belongs to.
 *
 * The bare `getComputedStyle` is the top-level window's; called on a node from
 * an iframe it answers about a document that is not the node's own.
 *
 * @param {Node} node
 * @returns {Window}
 */
export function viewOf(node) {
    return node.ownerDocument?.defaultView ?? window;
}

/**
 * The focused element of `node`'s own tree, or null.
 *
 * `document.activeElement` answers for the top-level document only: for a node
 * inside a shadow root it reports the shadow HOST, and for a node in an iframe
 * it reports that iframe. Either way an `indexOf` or a `contains` test against
 * nodes of `node`'s own tree silently misses, and the miss reads as "nothing is
 * focused" rather than as an error.
 *
 * A root's own `activeElement` is always a node OF that root's tree -- focus
 * deeper inside a nested shadow root is retargeted to its host -- so
 * `contains()` still answers correctly for anything below it.
 *
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
 * The innermost focused element, descending through every nested shadow root
 * AND every same-origin iframe.
 *
 * Use this when the element itself is the point -- blurring it, reading its
 * value. Use `getActiveElement` when the question is "where is focus, relative
 * to this tree".
 *
 * Both descents are needed and neither implies the other: an `<iframe>` IS the
 * active element of its parent document, and a shadow host IS the active
 * element of its own tree. `drag_session` walked iframes and stopped at shadow
 * roots; this walked shadow roots and stopped at iframes. A cross-origin frame
 * denies `contentDocument`, which ends the walk at the frame itself -- the best
 * answer available, and the one the DOM gives.
 *
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
            // A cross-origin frame denies `contentDocument`.
            inFrame = null;
        }
        if (!inFrame || inFrame === active) {
            return active;
        }
        active = inFrame;
    }
}

/**
 * Marks a host so its shadow tree can be FOUND by a selector.
 *
 * There is no selector for "has a shadow root", and no event when one is
 * attached: the only way to discover a host is to walk every element and read
 * `.shadowRoot`. Measured on an 8000-element tree, that scan costs ~1.3ms --
 * about +40% on `getTabableElements`, which runs on the focus-trap path per Tab
 * keypress. Paying that on every form so a handful of pages can be traversed
 * correctly is the wrong trade.
 *
 * An attribute moves the cost to attach time, where there is one host, and lets
 * the traversal find them with the query it was already running. Attach shadow
 * roots through here so they stay reachable; a raw `attachShadow` is invisible
 * to `getTabableElements` and to anything else that has to cross the boundary.
 *
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
    // A Document or a Window is always "visible". Comparing against the global
    // `document` / `window` only recognises the top-level pair, so an element
    // living in an iframe fell through to the measuring branch below.
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
// Hosts ride along in the same query, so finding them costs one more selector
// term rather than a second pass over every element.
const TABABLE_OR_HOST_SELECTOR = `${TABABLE_SELECTOR},${SHADOW_HOST_SELECTOR}`;

/**
 * @param {HTMLElement} el
 */
export function isFocusable(el) {
    return el.matches(FOCUSABLE_SELECTOR) && isVisible(el) && !el.closest("[inert]");
}

/**
 * Every tabable element of `container`, in tab order, descending into any
 * shadow root attached through `attachShadowRoot`.
 *
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
    // Almost every tree has no shadow host at all, and the combined query below
    // pays an `el.matches()` per result to tell hosts from tabables -- measured
    // at +13% on an 8000-element form, on the focus-trap path. One attribute
    // query answers whether that work is needed; it is indexed, so on the
    // common path it costs nothing and the loop is what it always was.
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
        // A host contributes its shadow tree AT ITS OWN POSITION, which is
        // where the browser puts it in the tab order.
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
