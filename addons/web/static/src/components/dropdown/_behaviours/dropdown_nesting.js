// @ts-check
/** @odoo-module native */

/** @module @web/components/dropdown/_behaviours/dropdown_nesting - Parent-child nesting state and close propagation logic for nested dropdowns */

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
        // O(1) guard first: every mounted dropdown receives this broadcast,
        // and on list/kanban pages ~all of them are closed — don't pay the
        // recursive children walk (with its array spread) for those.
        if (!(other.isOpen && this.isOpen)) {
            return;
        }
        // Prevents closing the dropdown when a change is coming from itself or from a children.
        if (this.shouldIgnoreChanges(other)) {
            return;
        }
        this.close();
    }
}

/**
 * Closes every open dropdown that isn't a parent of this one when this one
 * opens. Scoped to dropdowns sharing the same UI active element, so
 * dropdowns in different dialogs don't interfere.
 *
 * @param {import("@web/components/dropdown/dropdown_hooks").DropdownState} state
 * @returns
 */
export function useDropdownNesting(state) {
    const env = useEnv();
    const /** @type {any} */ envAny = env;
    const current = new DropdownNestingState({
        parent: envAny[DROPDOWN_NESTING],
        close: () => state.close(),
    });

    // Set up UI active element related behavior
    const uiService = useService("ui");
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
        /**@type {import("@web/services/navigation/navigation").NavigationOptions} */
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
