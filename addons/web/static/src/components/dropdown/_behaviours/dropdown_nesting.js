// @ts-check
/** @odoo-module native */

/** @module @web/components/dropdown/_behaviours/dropdown_nesting */

import { EventBus, onWillDestroy, useChildSubEnv, useEffect, useEnv } from "@odoo/owl";
import { localization } from "@web/core/l10n/localization";
import { useBus, useService } from "@web/core/utils/hooks";
import { disposableEffect } from "@web/core/utils/reactive";
export const DROPDOWN_NESTING = Symbol("dropdownNesting");
const BUS = new EventBus();

class DropdownNestingState {
    constructor({ parent, close }) {
        this._isOpen = false;
        this.parent = parent;
        this.children = new Set();
        this.close = close;
        /** @type {Element | undefined} */
        this.activeEl = undefined;

        parent?.children.add(this);
    }

    set isOpen(value) {
        this._isOpen = value;
        if (this._isOpen) {
            BUS.trigger("dropdown-opened", this);
        }
    }

    get isOpen() {
        return this._isOpen;
    }

    remove() {
        this.parent?.children.delete(this);
    }

    closeAllParents() {
        this.close();
        if (this.parent) {
            this.parent.closeAllParents();
        }
    }

    closeChildren() {
        this.children.forEach((child) => child.close());
    }

    shouldIgnoreChanges(other) {
        return (
            other === this ||
            other.activeEl !== this.activeEl ||
            [...this.children].some((child) => child.shouldIgnoreChanges(other))
        );
    }

    handleChange(other) {
        if (!(other.isOpen && this.isOpen)) {
            return;
        }
        if (this.shouldIgnoreChanges(other)) {
            return;
        }
        this.close();
    }
}

/**
 * @param {import("@web/components/dropdown/dropdown_hooks").DropdownState} state
 */
export function useDropdownNesting(state) {
    const env = useEnv();
    const /** @type {any} */ envAny = env;
    const current = new DropdownNestingState({
        parent: envAny[DROPDOWN_NESTING],
        close: () => state.close(),
    });

    const uiService = useService("ui");
    // Seed it now and settle it after the mount flush. The deferral is what
    // lets a dropdown mounting alongside a dialog see the dialog rather than
    // whatever was active before it; leaving the field undefined until then is
    // what made a dropdown that opens in the same tick it mounts read as
    // "somewhere else entirely" -- so its peers kept their menus open.
    current.activeEl = /** @type {any} */ (uiService.activeElement);
    useEffect(
        () => {
            queueMicrotask(() => {
                current.activeEl = /** @type {any} */ (uiService.activeElement);
            });
        },
        () => [],
    );

    useChildSubEnv(/** @type {any} */ ({ [DROPDOWN_NESTING]: current }));
    useBus(BUS, "dropdown-opened", (/** @type {any} */ { detail: other }) =>
        current.handleChange(other),
    );

    const disposeEffect = disposableEffect(
        (state) => {
            current.isOpen = state.isOpen;
        },
        [state],
    );

    onWillDestroy(() => {
        disposeEffect();
        current.remove();
    });

    const isDropdown = (target) => target?.classList.contains("o-dropdown");
    const isRTL = () => localization.direction === "rtl";

    return {
        get hasParent() {
            return Boolean(current.parent);
        },
        /** @type {import("@web/core/navigation/navigation").NavigationOptions} */
        navigationOptions: {
            onUpdated: (navigator) => {
                if (current.parent && !navigator.activeItem) {
                    navigator.items[0]?.setActive();
                }
            },
            hotkeys: {
                escape: () => current.close(),
                arrowleft: {
                    isAvailable: () => true,
                    callback: (navigator) => {
                        if (isRTL() && isDropdown(navigator.activeItem?.target)) {
                            navigator.activeItem?.select();
                        } else if (current.parent) {
                            current.close();
                        }
                    },
                },
                arrowright: {
                    isAvailable: () => true,
                    callback: (navigator) => {
                        if (isRTL() && current.parent) {
                            current.close();
                        } else if (isDropdown(navigator.activeItem?.target)) {
                            navigator.activeItem?.select();
                        }
                    },
                },
            },
        },
    };
}
