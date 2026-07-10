// @ts-check
/** @odoo-module native */

/** @module @web/legacy/js/public/minimal_dom - Async handler protection and button debouncing utilities for public DOM events */

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
        if (
            stopPropagation === true ||
            (stopPropagation && stopPropagation())
        ) {
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
        Promise.resolve(result).finally(_unlock);
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
    // Fallback: also wrap as an async handler in case some events ignore
    // the button's disabled state.
    fct = makeAsyncHandler(
        fct,
        preventDefault,
        stopPropagation,
        stopImmediatePropagation,
    );

    return function (ev) {
        const handlerResult = fct.apply(this, /** @type {any} */ (arguments));

        const buttonEl = /** @type {Element | null} */ (ev.target)?.closest(
            BUTTON_HANDLER_SELECTOR,
        );
        if (!(buttonEl instanceof HTMLElement)) {
            return handlerResult;
        }

        // Disable the button for the handler's action, or at least the
        // click debounce (without visual effect during the debounce itself).
        buttonEl.classList.add("pe-none");
        let showDebouncedLoading = false;
        const addLoadingIfPending = () => {
            buttonEl.classList.remove("pe-none");
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
