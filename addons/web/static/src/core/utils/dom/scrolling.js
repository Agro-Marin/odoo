// @ts-check
/** @odoo-module native */

import { browser } from "@web/core/browser/browser";
import { viewOf } from "@web/core/utils/dom/ui";

const SCROLL_SETTLE_TIMEOUT = 1000;

const SUPPORTS_SCROLLEND = "onscrollend" in window;

/**
 * @param {Element} el
 * @returns {HTMLElement | null}
 */
function parentAcrossRoots(el) {
    if (el.parentElement) {
        return el.parentElement;
    }
    const root = el.parentNode ?? el.getRootNode();
    return /** @type {ShadowRoot} */ (root)?.host ?? null;
}

function isScrollableX(/** @type {Element} */ el) {
    if (el.scrollWidth > el.clientWidth && el.clientWidth > 0) {
        return couldBeScrollableX(el);
    }
    return false;
}

export function couldBeScrollableX(/** @type {Element | null} */ el) {
    if (el) {
        const overflow = viewOf(el).getComputedStyle(el).getPropertyValue("overflow-x");
        if (/\bauto\b|\bscroll\b/.test(overflow)) {
            return true;
        }
    }
    return false;
}

/**
 * @param {HTMLElement | null} el
 * @returns {HTMLElement | null}
 */
export function closestScrollableX(el) {
    while (el) {
        if (isScrollableX(el)) {
            return el;
        }
        el = parentAcrossRoots(el);
    }
    return null;
}

export function isScrollableY(/** @type {Element | null} */ el) {
    if (el && el.scrollHeight > el.clientHeight && el.clientHeight > 0) {
        return couldBeScrollableY(el);
    }
    return false;
}

export function couldBeScrollableY(/** @type {Element | null} */ el) {
    if (el) {
        const overflow = viewOf(el).getComputedStyle(el).getPropertyValue("overflow-y");
        if (/\bauto\b|\bscroll\b/.test(overflow)) {
            return true;
        }
    }
    return false;
}

/**
 * @param {HTMLElement | null} el
 * @returns {HTMLElement | null}
 */
export function closestScrollableY(el) {
    while (el) {
        if (isScrollableY(el)) {
            return el;
        }
        el = parentAcrossRoots(el);
    }
    return null;
}

/**
 * @param {HTMLElement} element
 * @param {object} options
 * @param {HTMLElement} [options.scrollable]
 * @param {boolean} [options.isAnchor]
 * @param {ScrollBehavior} [options.behavior]
 * @param {number} [options.offset]
 * @returns {Promise<any[]> | void}
 */
export function scrollTo(element, options = {}) {
    const { behavior = "auto", isAnchor = false, offset = 0 } = options;
    const maybeScrollable = closestScrollableY(
        options.scrollable || element.parentElement,
    );
    if (!maybeScrollable) {
        return;
    }
    const scrollable = maybeScrollable;

    const scrollRect = scrollable.getBoundingClientRect();
    const elementRect = element.getBoundingClientRect();

    const scrollPromises = [];

    /**
     * @param {number} targetTop
     */
    function awaitScroll(targetTop) {
        const prevTop = scrollable.scrollTop;
        const maxTop = scrollable.scrollHeight - scrollable.clientHeight;
        const clampedTop = Math.max(0, Math.min(targetTop, maxTop));
        scrollable.scrollTo({ top: targetTop, behavior });
        if (Math.abs(clampedTop - prevTop) < 1) {
            return Promise.resolve();
        }
        return new Promise((resolve) => {
            let settled = false;
            /** @type {any} */
            let timer;
            /** @type {any} */
            let rafId;
            const finish = () => {
                if (settled) {
                    return;
                }
                settled = true;
                browser.clearTimeout(timer);
                if (rafId !== undefined) {
                    browser.cancelAnimationFrame(rafId);
                }
                scrollable.removeEventListener("scrollend", finish);
                resolve(undefined);
            };
            timer = browser.setTimeout(finish, SCROLL_SETTLE_TIMEOUT);
            if (SUPPORTS_SCROLLEND) {
                scrollable.addEventListener("scrollend", finish, { once: true });
            } else {
                let lastTop = scrollable.scrollTop;
                let stableFrames = 0;
                const check = () => {
                    if (settled) {
                        return;
                    }
                    const top = scrollable.scrollTop;
                    if (top === lastTop) {
                        if (++stableFrames >= 2) {
                            finish();
                            return;
                        }
                    } else {
                        stableFrames = 0;
                        lastTop = top;
                    }
                    rafId = browser.requestAnimationFrame(check);
                };
                rafId = browser.requestAnimationFrame(check);
            }
        });
    }

    if (elementRect.bottom > scrollRect.bottom && !isAnchor) {
        scrollPromises.push(
            awaitScroll(
                scrollable.scrollTop +
                    elementRect.top -
                    scrollRect.bottom +
                    Math.ceil(elementRect.height) +
                    offset,
            ),
        );
    } else if (elementRect.top < scrollRect.top || isAnchor) {
        scrollPromises.push(
            awaitScroll(
                scrollable.scrollTop - scrollRect.top + elementRect.top + offset,
            ),
        );

        if (options.isAnchor) {
            const parentScrollable = closestScrollableY(scrollable.parentElement);
            if (parentScrollable) {
                scrollPromises.push(
                    scrollTo(scrollable, {
                        behavior,
                        isAnchor: true,
                        scrollable: parentScrollable,
                    }),
                );
            }
        }
    }

    return Promise.all(scrollPromises);
}

export function compensateScrollbar(
    /** @type {HTMLElement | null} */ el,
    add = true,
    isScrollElement = true,
    cssProperty = "padding-right",
) {
    if (!el) {
        return;
    }
    const scrollableEl = isScrollElement ? el : closestScrollableY(el.parentElement);
    if (!scrollableEl) {
        return;
    }
    const isRTL = scrollableEl.classList.contains("o_rtl");
    if (isRTL) {
        cssProperty = cssProperty.replace("right", "left");
    }
    el.style.removeProperty(cssProperty);
    if (!add) {
        return;
    }
    const style = viewOf(el).getComputedStyle(el);
    const borderLeftWidth = Math.ceil(Number.parseFloat(style.borderLeftWidth));
    const borderRightWidth = Math.ceil(Number.parseFloat(style.borderRightWidth));
    const bordersWidth = borderLeftWidth + borderRightWidth;
    const newValue =
        Number.parseInt(/** @type {Record<string, any>} */ (style)[cssProperty], 10) +
        scrollableEl.offsetWidth -
        scrollableEl.clientWidth -
        bordersWidth;
    el.style.setProperty(cssProperty, `${newValue}px`, "important");
}

export function getScrollingElement(doc = window.document) {
    const baseScrollingElement = doc.scrollingElement;
    if (isScrollableY(baseScrollingElement)) {
        return baseScrollingElement;
    }
    const bodyHeight = Number.parseFloat(
        viewOf(doc.body).getComputedStyle(doc.body).height,
    );
    for (const el of doc.body.children) {
        if (bodyHeight - el.scrollHeight > 1.5) {
            continue;
        }
        if (isScrollableY(el)) {
            return el;
        }
    }
    return baseScrollingElement;
}

export function getScrollingTarget(
    /** @type {Document | Element} */ scrollingElement = window.document,
) {
    const doc = /** @type {Document} */ (scrollingElement.ownerDocument);
    return /** @type {Node} */ (scrollingElement) === doc.scrollingElement
        ? doc.defaultView
        : scrollingElement;
}
