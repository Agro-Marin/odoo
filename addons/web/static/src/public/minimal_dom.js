// @ts-check
/** @odoo-module native */

import { addLoadingEffect } from "@web/core/utils/dom/ui";

const LOADING_EFFECT_DELAY = 400;
export const BUTTON_HANDLER_SELECTOR =
    'a, button, input[type="submit"], input[type="button"], .btn';

/**
 * @param {(...args: any[]) => any} fct
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
        Promise.resolve(result).then(_unlock, _unlock);
        return result;
    };
}

/**
 * @param {(...args: any[]) => any} fct
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

        const currentEl = /** @type {Element | null} */ (ev.currentTarget);
        const buttonEl = currentEl?.matches?.(BUTTON_HANDLER_SELECTOR)
            ? currentEl
            : /** @type {Element | null} */ (ev.target)?.closest(
                  BUTTON_HANDLER_SELECTOR,
              );
        if (!(buttonEl instanceof HTMLElement)) {
            return handlerResult;
        }

        const wasUnclickable = buttonEl.classList.contains("pe-none");
        buttonEl.classList.add("pe-none");
        let showDebouncedLoading = false;
        /** @type {ReturnType<typeof setTimeout> | undefined} */
        let debounceTimer;
        const addLoadingIfPending = () => {
            clearTimeout(debounceTimer);
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
            new Promise((resolve) => {
                debounceTimer = setTimeout(resolve, LOADING_EFFECT_DELAY);
            }).then(() => {
                showDebouncedLoading = true;
            }),
        ]).then(addLoadingIfPending, addLoadingIfPending);

        return handlerResult;
    };
}
