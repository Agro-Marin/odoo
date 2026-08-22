// @ts-check
/** @odoo-module native */

/**
 * @typedef Position
 * @property {number} x
 * @property {number} y
 */

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
    if (el === document || el === window) {
        return true;
    }
    if (!el) {
        return false;
    }
    let _isVisible = false;
    if ("offsetWidth" in el && "offsetHeight" in el) {
        _isVisible = el.offsetWidth > 0 && el.offsetHeight > 0;
    } else if ("getBoundingClientRect" in el) {
        const rect = el.getBoundingClientRect();
        _isVisible = rect.width > 0 && rect.height > 0;
    }
    if (!_isVisible && getComputedStyle(el).display === "contents") {
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
 * @param {Element} activeElement
 * @param {string} selector
 * @returns {HTMLElement[]}
 */
export function getVisibleElements(activeElement, selector) {
    const visibleElements = [];
    /** @type {NodeListOf<HTMLElement>} */
    const elements = activeElement.querySelectorAll(selector);
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

/**
 * @param {HTMLElement} el
 */
export function isFocusable(el) {
    return (
        el.matches(FOCUSABLE_SELECTORS.join(",")) &&
        isVisible(el) &&
        !el.closest("[inert]")
    );
}

/**
 * @param {HTMLElement} [container=document.body]
 */
export function getTabableElements(container = document.body) {
    const elements = /** @type {HTMLElement[]} */ ([
        ...container.querySelectorAll(TABABLE_SELECTORS.join(",")),
    ]).filter((el) => el.tabIndex >= 0 && isVisible(el) && !el.closest("[inert]"));
    const byTabIndex = /** @type {Record<number, HTMLElement[]>} */ (
        Object.groupBy(elements, (el) => el.tabIndex)
    );

    const withTabIndexZero = byTabIndex[0] || [];
    delete byTabIndex[0];
    return [...Object.values(byTabIndex).flat(), ...withTabIndexZero];
}

/**
 * @param {HTMLElement} [container]
 * @returns {HTMLElement | null}
 */
export function getNextTabableElement(container = document.body) {
    const tabableElements = getTabableElements(container);
    const index = tabableElements.indexOf(/** @type {any} */ (document.activeElement));
    return index === -1 ? tabableElements[0] : tabableElements[index + 1] || null;
}

/**
 * @param {HTMLElement} [container]
 * @returns {HTMLElement | undefined | null}
 */
export function getPreviousTabableElement(container = document.body) {
    const tabableElements = getTabableElements(container);
    const index = tabableElements.indexOf(/** @type {any} */ (document.activeElement));
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
    const loaderEl = document.createElement("span");
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
