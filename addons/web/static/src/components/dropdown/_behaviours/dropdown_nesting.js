// @ts-check
/** @odoo-module native */

import { onWillDestroy, useChildSubEnv, useEnv } from "@odoo/owl";
import { DropdownEvent } from "@web/core/events";
import { localization } from "@web/core/l10n/localization";
import { useBus, useEventBus, useService } from "@web/core/utils/hooks";
import { useLayoutEffect } from "@web/core/utils/layout_effect";
import { effect } from "@web/core/utils/reactive";
const DROPDOWN_NESTING = Symbol("dropdownNesting");

/** @param {DropdownNestingState} nesting */
function provideDropdownNesting(nesting) {
    useChildSubEnv(/** @type {any} */ ({ [DROPDOWN_NESTING]: nesting }));
}

/** @returns {DropdownNestingState | undefined} */
export function useParentDropdownNesting() {
    return /** @type {any} */ (useEnv())[DROPDOWN_NESTING];
}

class DropdownNestingState {
    constructor({ parent, close, bus }) {
        this._isOpen = false;
        this.parent = parent;
        this.children = new Set();
        this.close = close;
        this.bus = bus;
        /** @type {Element | undefined} */
        this.activeEl = undefined;

        parent?.children.add(this);
    }

    set isOpen(value) {
        this._isOpen = value;
        if (this._isOpen) {
            this.bus.trigger(DropdownEvent.OPENED, this);
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

    /**
     * @param {DropdownNestingState} other
     * @returns {boolean}
     */
    shouldIgnoreChanges(other) {
        return (
            other === this ||
            other.activeEl !== this.activeEl ||
            this.isAncestorOf(other)
        );
    }

    /**
     * @param {DropdownNestingState} other
     * @returns {boolean}
     */
    isAncestorOf(other) {
        for (let node = other.parent; node; node = node.parent) {
            if (node === this) {
                return true;
            }
        }
        return false;
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

/** @param {import("@web/components/dropdown/dropdown_hook").DropdownState} state */
export function useDropdownNesting(state) {
    const bus = useEventBus();
    const current = new DropdownNestingState({
        parent: useParentDropdownNesting(),
        close: () => state.close(),
        bus,
    });

    const uiService = useService("ui");
    current.activeEl = /** @type {any} */ (uiService.activeElement);
    useLayoutEffect(
        () => {
            queueMicrotask(() => {
                current.activeEl = /** @type {any} */ (uiService.activeElement);
            });
        },
        () => [],
    );

    provideDropdownNesting(current);
    useBus(bus, DropdownEvent.OPENED, (/** @type {any} */ { detail: other }) =>
        current.handleChange(other),
    );

    const disposeEffect = effect(
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
