// @ts-check
/** @odoo-module native */

/** @module @web/core/utils/dom/scrolling - Scroll detection, scrollIntoView, and scrollbar compensation utilities */

import { browser } from "@web/core/browser/browser";

/**
 * Maximum time (ms) to wait for a scroll to settle before resolving anyway.
 * Guards against environments that never fire "scrollend" (older Safari,
 * embedded webviews) and against the scrollable being detached mid-scroll.
 */
const SCROLL_SETTLE_TIMEOUT = 1000;

function isScrollableX(/** @type {Element} */ el) {
    if (el.scrollWidth > el.clientWidth && el.clientWidth > 0) {
        return couldBeScrollableX(el);
    }
    return false;
}

export function couldBeScrollableX(/** @type {Element | null} */ el) {
    if (el) {
        const overflow = getComputedStyle(el).getPropertyValue("overflow-x");
        if (/\bauto\b|\bscroll\b/.test(overflow)) {
            return true;
        }
    }
    return false;
}

/**
 * Get the closest horizontally scrollable for a given element.
 *
 * @param {HTMLElement | null} el
 * @returns {HTMLElement | null}
 */
export function closestScrollableX(el) {
    while (el) {
        if (isScrollableX(el)) {
            return el;
        }
        el = el.parentElement;
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
        const overflow = getComputedStyle(el).getPropertyValue("overflow-y");
        if (/\bauto\b|\bscroll\b/.test(overflow)) {
            return true;
        }
    }
    return false;
}

/**
 * Get the closest vertically scrollable for a given element.
 *
 * @param {HTMLElement | null} el
 * @returns {HTMLElement | null}
 */
export function closestScrollableY(el) {
    while (el) {
        if (isScrollableY(el)) {
            return el;
        }
        el = el.parentElement;
    }
    return null;
}

/**
 * Ensures that `element` will be visible in its `scrollable`.
 *
 * @param {HTMLElement} element
 * @param {object} options
 * @param {HTMLElement} [options.scrollable] a scrollable area
 * @param {boolean} [options.isAnchor] states if the scroll is to an anchor
 * @param {ScrollBehavior} [options.behavior] "smooth", "instant", "auto"
 * @param {number} [options.offset] applies a vertical offset
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
    // Bind a non-null const so the nested awaitScroll closure sees HTMLElement:
    // TS does not carry the guard's narrowing across a function boundary.
    const scrollable = maybeScrollable;

    const scrollRect = scrollable.getBoundingClientRect();
    const elementRect = element.getBoundingClientRect();

    const scrollPromises = [];

    /**
     * Wait for the scroll to settle, but resolve immediately if no actual
     * scrolling occurs. Never hangs: it feature-detects "scrollend" and always
     * races the wait against a max-duration timer (which also cleans up the
     * once-listener if the scrollable is detached mid-scroll).
     * @param {number} targetTop
     */
    function awaitScroll(targetTop) {
        const prevTop = scrollable.scrollTop;
        scrollable.scrollTo({ top: targetTop, behavior });
        if (scrollable.scrollTop === prevTop) {
            // No scroll happened (already at target) — resolve immediately.
            // For smooth scrolling the browser may not have updated scrollTop
            // synchronously, but if it truly was a no-op, scrollend won't fire
            // and we'd hang. Resolve now; if a smooth scroll does start, the
            // caller's Promise.all simply won't wait for its end — acceptable.
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
            // Always race with a max-duration timer so the promise can never
            // hang if "scrollend" never fires or the element is removed.
            timer = browser.setTimeout(finish, SCROLL_SETTLE_TIMEOUT);
            if ("onscrollend" in scrollable) {
                scrollable.addEventListener("scrollend", finish, { once: true });
            } else {
                // No "scrollend" support (older Safari, embedded webviews):
                // settle once scrollTop stops changing across frames.
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
    const style = window.getComputedStyle(el);
    // Round up to the nearest integer to be as close as possible to
    // the correct value in case of browser zoom.
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

export function getScrollingElement(document = window.document) {
    const baseScrollingElement = document.scrollingElement;
    if (isScrollableY(baseScrollingElement)) {
        return baseScrollingElement;
    }
    const bodyHeight = Number.parseFloat(window.getComputedStyle(document.body).height);
    for (const el of document.body.children) {
        // Search for a body child which is at least as tall as the body
        // and which has the ability to scroll if enough content in it. If
        // found, suppose this is the top scrolling element.
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
