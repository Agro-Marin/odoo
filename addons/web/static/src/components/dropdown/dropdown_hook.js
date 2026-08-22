// @ts-check
/** @odoo-module native */

import { useEnv, useState } from "@odoo/owl";
import { DROPDOWN_NESTING } from "@web/components/dropdown/_behaviours/dropdown_nesting";
import { SignalStore } from "@web/core/utils/reactive";
/**
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
        if (this.isOpen) {
            return;
        }
        this.isOpen = true;
        this._onOpen?.();
    }
    close() {
        if (!this.isOpen) {
            return;
        }
        this.isOpen = false;
        this._onClose?.();
    }
}

/**
 * @param {{ onOpen?: Function, onClose?: Function }} [callbacks]
 * @returns {DropdownState}
 */
export function useDropdownState({ onOpen, onClose } = /** @type {any} */ ({})) {
    return useState(new DropdownState({ onOpen, onClose }));
}

export function useDropdownCloser() {
    const env = useEnv();
    const dropdown = /** @type {any} */ (env)[DROPDOWN_NESTING];
    return {
        close: () => dropdown?.close(),
        closeChildren: () => dropdown?.closeChildren(),
        closeAll: () => dropdown?.closeAllParents(),
    };
}
