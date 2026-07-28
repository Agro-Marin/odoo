// @ts-check
/** @odoo-module native */

/** @module @web/public/minimal_dom - Async handler protection and button debouncing utilities for public DOM events */

import { addLoadingEffect } from "@web/core/utils/dom/ui";

export const DEBOUNCE = 400;
export const BUTTON_HANDLER_SELECTOR =
    'a, button, input[type="submit"], input[type="button"], .btn';

/**
 * Wraps a handler so a previous (possibly async) call must finish before it
 * can run again. While locked, the wrapped handler's own preventDefault/
 * stopPropagation calls are skipped too — use the preventDefault/
 * stopPropagation/stopImmediatePropagation args to still apply them.
 *
 * Releasing the lock means observing the wrapped call's outcome, so a failure
 * is carried by the returned promise and by nothing else. A caller that
 * discards that promise — a raw DOM listener does — therefore has to report its
 * own errors; see `waitForLazyAndRetrigger`.
 *
 * @param {(...args: any[]) => any} fct
 *      The function which is to be used as a handler. If a promise
 *      is returned, it is used to determine when the handler's action is
 *      finished.
 * @param {((...args: any[]) => boolean) | boolean} [preventDefault]
 * @param {((...args: any[]) => boolean) | boolean} [stopPropagation]
 * @param {((...args: any[]) => boolean) | boolean} [stopImmediatePropagation]
 * @returns {(ev: Event) => any}
 */
export function makeAsyncHandler(
    fct,
    preventDefault,
    stopPropagation,
    stopImmediatePropagation,
) {
    let pending = false;
    function _isLocked() {
        return pending;
    }
    function _lock() {
        pending = true;
    }
    function _unlock() {
        pending = false;
    }
    return function (ev) {
        if (preventDefault === true || (preventDefault && preventDefault())) {
            ev.preventDefault();
        }
        if (stopPropagation === true || (stopPropagation && stopPropagation())) {
            ev.stopPropagation();
        }
        if (
            stopImmediatePropagation === true ||
            (stopImmediatePropagation && stopImmediatePropagation())
        ) {
            ev.stopImmediatePropagation();
        }

        if (_isLocked()) {
            return;
        }

        _lock();
        let result;
        try {
            result = fct.apply(this, /** @type {any} */ (arguments));
        } catch (error) {
            _unlock();
            throw error;
        }
        // `.then(_unlock, _unlock)` and not `.finally(_unlock)`: `finally`
        // forwards the rejection to a derived promise nobody holds, so a
        // failing async handler was reported as an unhandled rejection on top
        // of — or instead of — reaching whoever awaits the returned one
        Promise.resolve(result).then(_unlock, _unlock);
        return result;
    };
}

/**
 * Debounced version of a function used as a button click handler: also
 * disables the button for the debounce and/or async-action duration.
 *
 * Limitation: if two handlers are put on the same button, the button will
 * become enabled again once any handler's action finishes (multiple click
 * handlers should however not be bound to the same button).
 *
 * @param {(...args: any[]) => any} fct
 *      The function which is to be used as a button click handler. If a
 *      promise is returned, it is used to determine when the button can be
 *      re-enabled.
 * @param {((...args: any[]) => boolean) | boolean} [preventDefault]
 * @param {((...args: any[]) => boolean) | boolean} [stopPropagation]
 * @param {((...args: any[]) => boolean) | boolean} [stopImmediatePropagation]
 * @returns {(ev: Event) => any}
 */
export function makeButtonHandler(
    fct,
    preventDefault,
    stopPropagation,
    stopImmediatePropagation,
) {
    fct = makeAsyncHandler(
        fct,
        preventDefault,
        stopPropagation,
        stopImmediatePropagation,
    );

    return function (ev) {
        const handlerResult = fct.apply(this, /** @type {any} */ (arguments));

        // the element the listener is bound to, when that is itself a control:
        // `target.closest()` walks up from whatever was clicked and stops at the
        // INNERMOST match, so a control wrapping a link (`<div class="btn"><a>`)
        // had the effect put on the link instead of on the button that owns the
        // handler. The fallback still covers a delegated listener, whose
        // currentTarget is a container rather than a control.
        const currentEl = /** @type {Element | null} */ (ev.currentTarget);
        const buttonEl = currentEl?.matches?.(BUTTON_HANDLER_SELECTOR)
            ? currentEl
            : /** @type {Element | null} */ (ev.target)?.closest(
                  BUTTON_HANDLER_SELECTOR,
              );
        if (!(buttonEl instanceof HTMLElement)) {
            return handlerResult;
        }

        // a control the page had already made unclickable stays that way: the
        // undo below used to drop `pe-none` unconditionally, handing back the
        // pointer. `pointer-events: none` only removes the element from hit
        // testing, so a click still reaches it through the keyboard (Enter on a
        // focused button — measured) or through `el.click()`, and that one
        // activation was enough to make it mouse-clickable for good.
        const wasUnclickable = buttonEl.classList.contains("pe-none");
        buttonEl.classList.add("pe-none");
        let showDebouncedLoading = false;
        const addLoadingIfPending = () => {
            if (!wasUnclickable) {
                buttonEl.classList.remove("pe-none");
            }
            if (showDebouncedLoading) {
                const restore = /** @type {(value: any) => any} */ (
                    addLoadingEffect(/** @type {HTMLButtonElement} */ (buttonEl))
                );
                Promise.resolve(handlerResult).then(restore, restore);
            }
        };
        Promise.race([
            handlerResult,
            new Promise((resolve) => setTimeout(resolve, DEBOUNCE)).then(() => {
                showDebouncedLoading = true;
            }),
        ]).then(addLoadingIfPending, addLoadingIfPending);

        return handlerResult;
    };
}
