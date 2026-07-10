// @ts-check
/** @odoo-module native */

/** @module @web/components/dropdown/dropdown_hooks - Reactive DropdownState class and hooks for open/close control */

import { useEnv, useState } from "@odoo/owl";
import { DROPDOWN_NESTING } from "@web/components/dropdown/_behaviours/dropdown_nesting";
import { SignalStore } from "@web/core/utils/reactive";
/**
 * State of a dropdown; pass the instance to `<Dropdown state="dropdownState">`.
 * @param {{ onOpen?: Function, onClose?: Function }} [callbacks]
 */
export class DropdownState extends SignalStore {
    isOpen = false;
    constructor({ onOpen, onClose } = /** @type {any} */ ({})) {
        super();
        this._onOpen = onOpen;
        this._onClose = onClose;
    }
    open() {
        this.isOpen = true;
        this._onOpen?.();
    }
    close() {
        this.isOpen = false;
        this._onClose?.();
    }
}

/**
 * Hook used to interact with the Dropdown state and to subscribe to changes.
 * @param {{ onOpen?: Function, onClose?: Function }} [callbacks]
 * @returns {DropdownState}
 */
export function useDropdownState({ onOpen, onClose } = /** @type {any} */ ({})) {
    return useState(new DropdownState({ onOpen, onClose }));
}

/** Lets a component control how and when a wrapping dropdown closes. */
export function useDropdownCloser() {
    const env = useEnv();
    const dropdown = /** @type {any} */ (env)[DROPDOWN_NESTING];
    return {
        close: () => dropdown?.close(),
        closeChildren: () => dropdown?.closeChildren(),
        closeAll: () => dropdown?.closeAllParents(),
    };
}
