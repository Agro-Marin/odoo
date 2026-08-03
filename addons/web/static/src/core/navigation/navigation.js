// @ts-check
/** @odoo-module native */

/** @module @web/core/navigation/navigation */

import { onWillDestroy, reactive, useEffect, useRef, useState } from "@odoo/owl";
import { browser } from "@web/core/browser/browser";
import { deepMerge } from "@web/core/utils/collections/objects";
import { scrollTo } from "@web/core/utils/dom/scrolling";
import { useService } from "@web/core/utils/hooks";
import { throttleForAnimation } from "@web/core/utils/timing";
export const ACTIVE_ELEMENT_CLASS = "focus";

const ARIA_SELECTED_ROLES = new Set([
    "columnheader",
    "gridcell",
    "option",
    "row",
    "rowheader",
    "tab",
    "treeitem",
]);

const ARIA_ACTIVEDESCENDANT_ROLES = new Set([
    "application",
    "combobox",
    "grid",
    "group",
    "listbox",
    "menu",
    "menubar",
    "radiogroup",
    "row",
    "searchbox",
    "spinbutton",
    "tablist",
    "textbox",
    "toolbar",
    "tree",
    "treegrid",
]);

/**
 * @param {HTMLElement} el
 * @returns {boolean}
 */
function supportsAriaSelected(el) {
    return ARIA_SELECTED_ROLES.has(el.getAttribute("role") ?? "");
}

let navigationItemId = 0;

class NavigationItem {
    /** @type {number} */
    index = -1;

    /**
     * @type {HTMLElement}
     */
    el = undefined;

    /**
     * @type {HTMLElement}
     */
    target = undefined;

    /**
     * @param {{ index: number, el: HTMLElement, options: NavigationOptions, navigator: Navigator }} param0
     */
    constructor({ index, el, options, navigator }) {
        this.index = index;

        /** @private */
        this._options = options;

        /**
         * @private
         * @type {Navigator}
         */
        this._navigator = navigator;

        this.el = el;
        if (this._options.shouldFocusChildInput) {
            const subInput = el.querySelector(
                ":scope input, :scope button, :scope textarea",
            );
            this.target = /** @type {HTMLElement} */ (subInput || el);
        } else {
            this.target = el;
        }

        // Whoever writes this attribute first owns it. Left to itself the
        // navigator uses `aria-selected` for the cursor, which is the combobox
        // convention and stays the default. But it is also the only channel a
        // multi-select listbox has for "this one is held", and there the cursor
        // would report every held option as unheld -- so a component with
        // something of its own to say renders the attribute itself and keeps
        // it. `aria-activedescendant` carries the cursor either way.
        /** @private */
        this._ownsAriaSelected =
            supportsAriaSelected(this.el) && !this.el.hasAttribute("aria-selected");
        if (this._ownsAriaSelected) {
            this.el.ariaSelected = "false";
        }

        const onFocus = () => this.setActive(false);
        const onMouseMove = () => this._onMouseMove();

        this.target.addEventListener("focus", onFocus);
        this.target.addEventListener("mousemove", onMouseMove);

        this._removeListeners = () => {
            this.target.removeEventListener("focus", onFocus);
            this.target.removeEventListener("mousemove", onMouseMove);
        };
    }

    select() {
        this.setActive();
        this.target.click();
    }

    setActive(focus = true) {
        scrollTo(this.target);
        this._navigator._setActiveItem(this.index);
        this.target.classList.add(ACTIVE_ELEMENT_CLASS);
        this._setAriaSelected("true");

        if (focus && !this._options.virtualFocus) {
            this._navigator._throttledFocus.cancel();
            this._navigator._throttledFocus(this.target);
        }
    }

    setInactive(blur = true) {
        this.target.classList.remove(ACTIVE_ELEMENT_CLASS);
        this._setAriaSelected("false");
        if (blur && !this._options.virtualFocus) {
            this.target.blur();
        }
    }

    /**
     * @private
     * @param {"true" | "false"} value
     */
    _setAriaSelected(value) {
        if (this._ownsAriaSelected) {
            this.el.ariaSelected = value;
        }
    }

    /**
     * @private
     */
    _onMouseMove() {
        if (
            this._navigator.activeItem !== this &&
            this._navigator._isNavigationAvailable(this.target)
        ) {
            this.setActive(false);
            this._options.onMouseEnter?.(this);
        }
    }
}

export class Navigator {
    /** @type {Array<NavigationItem>} */
    items = [];

    /**
     * @private
     * @type {Array<() => void>}
     */ _hotkeyRemoves = [];
    /**
     * @private
     * @type {import("@web/core/hotkeys/hotkey_service").HotkeyService}
     */ _hotkeyService = undefined;

    /**
     * @param {NavigationOptions} options
     * @param {import("@web/core/hotkeys/hotkey_service").HotkeyService} hotkeyService
     */
    constructor(options, hotkeyService) {
        this._hotkeyService = hotkeyService;
        /** @private */
        this._throttledFocus = throttleForAnimation((/** @type {HTMLElement} */ el) =>
            el?.focus(),
        );
        this.state = reactive({
            /** @type {number} */
            activeItemIndex: -1,
            /** @type {HTMLElement | null} */
            activeItemEl: null,
            itemsRevision: 0,
        });

        const defaultOptions = {
            isNavigationAvailable: (
                /** @type {{ navigator: Navigator, target: HTMLElement }} */ { target },
            ) =>
                this.contains(target) && (this.isFocused || this._options.virtualFocus),
            shouldFocusChildInput: true,
            shouldFocusFirstItem: false,
            shouldRegisterHotkeys: true,
            virtualFocus: false,
            hotkeys: {
                home: () => this.items[0]?.setActive(),
                end: () => this.items.at(-1)?.setActive(),
                tab: {
                    callback: () => this.next(),
                    bypassEditableProtection: true,
                },
                "shift+tab": {
                    callback: () => this.previous(),
                    bypassEditableProtection: true,
                },
                arrowdown: {
                    callback: () => this.next(),
                    bypassEditableProtection: true,
                },
                arrowup: {
                    callback: () => this.previous(),
                    bypassEditableProtection: true,
                },
                enter: {
                    isAvailable: (
                        /** @type {{ navigator: Navigator, target: HTMLElement }} */ {
                            navigator,
                        },
                    ) => Boolean(navigator.activeItem),
                    callback: () => {
                        const item = this.activeItem || this.items[0];
                        item?.select();
                    },
                    bypassEditableProtection: true,
                },
            },
        };
        // An option declared as an accessor keeps answering for this
        // navigator's life; `mergeNavigationOptions` is the only combinator
        // that does not flatten it into the value it happened to hold.
        /** @private */
        this._options = mergeNavigationOptions(defaultOptions, options);

        if (this._options.shouldRegisterHotkeys) {
            this.registerHotkeys();
        }
    }

    /** @type {number} */
    get activeItemIndex() {
        return this.state.activeItemIndex;
    }
    set activeItemIndex(value) {
        this.state.activeItemIndex = value;
    }

    /** @type {NavigationItem | null} */
    get activeItem() {
        const idx = this.state.activeItemIndex;
        return idx >= 0 ? (this.items[idx] ?? null) : null;
    }

    /**
     * @type {boolean}
     */
    get hasActiveItem() {
        return Boolean(this.activeItem?.el.isConnected);
    }

    /**
     * @type {boolean}
     */
    get isFocused() {
        return this.items.some((item) => item.target.contains(document.activeElement));
    }

    next() {
        const hasActive = this.hasActiveItem;
        if (!hasActive) {
            this.items[0]?.setActive();
        } else {
            this.items[(this.activeItemIndex + 1) % this.items.length]?.setActive();
        }
    }

    previous() {
        const hasActive = this.hasActiveItem;
        const index = this.activeItemIndex - 1;
        if (!hasActive || index < 0) {
            this.items.at(-1)?.setActive();
        } else {
            this.items[index]?.setActive();
        }
    }

    update() {
        const oldItems = new Map(this.items.map((item) => [item.el, item]));
        const oldActiveItem = this.activeItem;
        const activeElement = document.activeElement;
        const focusWasInMenu =
            this.isFocused || !activeElement || activeElement === document.body;
        const elements = this._options.getItems();
        this.items = [];

        let didUpdate = elements.length !== oldItems.size;
        for (let index = 0; index < elements.length; index++) {
            const element = elements[index];

            let item = oldItems.get(element);
            if (item) {
                if (item.index !== index) {
                    item.index = index;
                    didUpdate = true;
                }
                oldItems.delete(element);
            } else {
                didUpdate = true;
                item = new NavigationItem({
                    index,
                    el: element,
                    options: this._options,
                    navigator: this,
                });
            }
            this.items.push(item);
        }

        for (const item of oldItems.values()) {
            item._removeListeners();
        }

        if (didUpdate) {
            const activeItemIndex = oldActiveItem?.el.isConnected
                ? this.items.findIndex((item) => item.el === oldActiveItem.el)
                : -1;
            const focusedElementIndex = this.items.findIndex(
                (item) => item.el === document.activeElement,
            );
            if (activeItemIndex > -1) {
                this._updateActiveItemIndex(activeItemIndex, focusWasInMenu);
            } else if (this.activeItemIndex >= 0) {
                const closest = Math.min(this.activeItemIndex, elements.length - 1);
                this._updateActiveItemIndex(closest, focusWasInMenu);
            } else if (focusedElementIndex >= 0) {
                this._updateActiveItemIndex(focusedElementIndex, true);
            } else {
                this._updateActiveItemIndex(-1, focusWasInMenu);
            }

            this._options.onUpdated?.(this);

            if (this._options.shouldFocusFirstItem) {
                this.items[0]?.setActive();
            }
            this.state.itemsRevision++;
        }
    }

    /**
     * @param {HTMLElement} target
     * @returns {boolean}
     */
    contains(target) {
        return this.items.some((item) => item.target.contains(target));
    }

    registerHotkeys() {
        if (this._hotkeyRemoves.length) {
            return;
        }

        for (const [hotkey, hotkeyInfo] of Object.entries(this._options.hotkeys)) {
            if (!hotkeyInfo) {
                continue;
            }

            const callback =
                typeof hotkeyInfo == "function" ? hotkeyInfo : hotkeyInfo.callback;
            if (!callback) {
                continue;
            }

            const isAvailable = hotkeyInfo?.isAvailable ?? (() => true);
            const bypassEditableProtection =
                hotkeyInfo?.bypassEditableProtection ?? false;
            const allowRepeat = hotkeyInfo?.allowRepeat ?? true;

            this._hotkeyRemoves.push(
                this._hotkeyService.add(hotkey, async () => await callback(this), {
                    global: true,
                    allowRepeat,
                    isAvailable: (/** @type {HTMLElement} */ target) =>
                        this._isNavigationAvailable(target) &&
                        isAvailable({ navigator: this, target }),
                    bypassEditableProtection,
                }),
            );
        }
    }

    unregisterHotkeys() {
        for (const removeHotkey of this._hotkeyRemoves) {
            removeHotkey();
        }
        this._hotkeyRemoves = [];
    }

    _destroy() {
        this._throttledFocus.cancel();
        for (const item of this.items) {
            item._removeListeners();
        }
        this.items = [];
        this.state.activeItemIndex = -1;
        this.state.activeItemEl = null;
        this.state.itemsRevision++;
        this._syncActiveDescendant();
        this.unregisterHotkeys();
    }

    /**
     * @private
     * @returns {HTMLElement | null}
     */
    _getAriaOwner() {
        const container = this._options.getContainer?.() ?? null;
        const hasCompositeRole = (/** @type {Element | null} */ el) =>
            Boolean(el) &&
            ARIA_ACTIVEDESCENDANT_ROLES.has(el.getAttribute("role") ?? "");
        if (this._options.virtualFocus) {
            const focused = /** @type {HTMLElement | null} */ (
                container?.ownerDocument.activeElement ?? null
            );
            if (focused && focused !== container && hasCompositeRole(focused)) {
                return focused;
            }
        }
        return hasCompositeRole(container) ? container : null;
    }

    /**
     * @private
     */
    _syncActiveDescendant() {
        const owner = this._getAriaOwner();
        if (this._ariaOwner && this._ariaOwner !== owner) {
            this._ariaOwner.removeAttribute("aria-activedescendant");
        }
        this._ariaOwner = owner;
        if (!owner) {
            return;
        }
        const activeEl = this.state.activeItemEl;
        if (!activeEl) {
            owner.removeAttribute("aria-activedescendant");
            return;
        }
        if (!activeEl.id) {
            activeEl.id = `o-navigation-item-${++navigationItemId}`;
        }
        owner.setAttribute("aria-activedescendant", activeEl.id);
    }

    /**
     * @param {number} index
     */
    _setActiveItem(index) {
        this.activeItem?.setInactive(false);
        const item = index >= 0 ? this.items[index] : undefined;
        this.state.activeItemEl = item?.el ?? null;
        this.state.activeItemIndex = item ? index : -1;
        this._syncActiveDescendant();
        if (item) {
            this._options.onItemActivated?.(item.el);
        }
    }

    /**
     * @param {HTMLElement | undefined | null} el
     * @returns {boolean}
     */
    isActiveEl(el) {
        return Boolean(el) && this.state.activeItemEl === el;
    }

    /**
     * @private
     * @param {number} index
     * @param {boolean} [mayFocus=true]
     */
    _updateActiveItemIndex(index, mayFocus = true) {
        if (this.items[index]) {
            const shouldFocus =
                mayFocus &&
                !this.items.some((item) => item.target === document.activeElement);
            this.items[index].setActive(shouldFocus);
        } else {
            this._setActiveItem(-1);
        }
    }

    /**
     * @param {HTMLElement} target
     */
    _isNavigationAvailable(target) {
        return this._options.isNavigationAvailable({ navigator: this, target });
    }

    /**
     * @param {EventTarget | null} target
     */
    _checkFocus(target) {
        const isEl = target instanceof HTMLElement;
        const navOK = isEl && this._isNavigationAvailable(target);
        if (!isEl || !navOK) {
            this._setActiveItem(-1);
        }
    }
}

/**
 * A plain value in this object is read once, when the navigator is built. An
 * option that has to follow something that moves is declared as a getter
 * instead, and stays live for the navigator's whole life -- see
 * `keepLiveOptions`, which is what carries the accessors across the copy and
 * the merge that would otherwise flatten them into values.
 *
 * @typedef {Object} NavigationOptions
 * @property {() => HTMLElement[]} [getItems]
 * @property {() => HTMLElement | null} [getContainer]
 * @property {(info: { navigator: Navigator, target: HTMLElement }) => boolean} [isNavigationAvailable]
 * @property {Record<string, any>} [hotkeys]
 * @property {Function} [onUpdated]
 * @property {Function} [onItemActivated]
 * @property {Function} [onMouseEnter]
 * @property {boolean} [virtualFocus]
 * @property {boolean} [shouldFocusChildInput]
 * @property {boolean} [shouldFocusFirstItem]
 * @property {boolean} [shouldRegisterHotkeys]
 */

/**
 * @typedef {Object} HotkeyOptions
 * @property {hotkeyHandler} callback
 * @property {(info: { navigator: Navigator, target: HTMLElement }) => boolean} [isAvailable]
 * @property {boolean} [bypassEditableProtection]
 * @property {boolean} [allowRepeat]
 */

/**
 * @callback hotkeyHandler
 * @param {Navigator} navigator
 */

/**
 * Copying an object -- by spread, by `deepMerge`, by anything that reads a key
 * and writes its value -- turns a getter into whatever it returned at that
 * moment. Restoring the accessors afterwards is what lets an option follow
 * something that moves rather than freezing at setup.
 *
 * @template {Object} T
 * @param {T} copy the flattened result
 * @param {NavigationOptions} source the object the accessors were declared on
 * @returns {T} `copy`
 */
export function keepLiveOptions(copy, source) {
    for (const key of Reflect.ownKeys(source)) {
        const descriptor = Object.getOwnPropertyDescriptor(source, key);
        if (descriptor?.get) {
            Object.defineProperty(copy, key, descriptor);
        }
    }
    return copy;
}

/**
 * Combine option sources, later winning over earlier, **without flattening
 * accessors**.
 *
 * This exists because `keepLiveOptions` alone could not hold the invariant. It
 * has to be applied at *every* place options are copied, and the rule lived in
 * a comment rather than in the API — so `Dropdown`, the component that actually
 * assembles options out of its props, merged them with a bare
 * `{...deepMerge(nesting, props)}` and froze every accessor its caller had
 * declared. `SelectMenu`'s `get virtualFocus()` was read once at setup, while
 * the menu still had a search box, and answered `true` forever after; the
 * navigator therefore kept a virtual cursor with nothing to park it on and the
 * arrow keys moved no real focus. Merging is the operation that loses
 * accessors, so merging is where preserving them belongs.
 *
 * Last-wins applies to the *declaration*, not just the value: if a later source
 * defines a key as a plain value it must beat an earlier source's getter, so
 * only the final declaration of each key is reinstated.
 *
 * @param {...(NavigationOptions | undefined)} sources
 * @returns {NavigationOptions} a fresh object; no source is mutated
 */
export function mergeNavigationOptions(...sources) {
    const present = sources.filter(Boolean);
    const merged = present.reduce(
        (acc, source) => deepMerge(acc, source),
        /** @type {any} */ ({}),
    );
    /** @type {Map<PropertyKey, PropertyDescriptor>} */
    const lastDeclaration = new Map();
    for (const source of present) {
        for (const key of Reflect.ownKeys(source)) {
            const descriptor = Object.getOwnPropertyDescriptor(source, key);
            if (descriptor?.enumerable) {
                lastDeclaration.set(key, descriptor);
            }
        }
    }
    for (const [key, descriptor] of lastDeclaration) {
        if (descriptor.get) {
            Object.defineProperty(merged, key, descriptor);
        }
    }
    return merged;
}

/**
 * A default for an option the caller left out. Defined rather than assigned:
 * the caller may have declared the key as a getter with no setter, and an
 * assignment onto one of those throws.
 *
 * @param {Object} options
 * @param {string} key
 * @param {any} value
 */
function defineOption(options, key, value) {
    Object.defineProperty(options, key, {
        value,
        writable: true,
        enumerable: true,
        configurable: true,
    });
}

/**
 * @param {string|Object} containerRef
 * @param {NavigationOptions} options
 * @returns {Navigator}
 */
export function useNavigation(containerRef, options = {}) {
    containerRef =
        typeof containerRef === "string" ? useRef(containerRef) : containerRef;

    const newOptions = mergeNavigationOptions(options);
    if (!newOptions.getItems) {
        defineOption(
            newOptions,
            "getItems",
            () =>
                /** @type {any} */ (containerRef).el?.querySelectorAll(
                    ":scope .o-navigable",
                ) ?? [],
        );
    }
    if (!newOptions.getContainer) {
        defineOption(
            newOptions,
            "getContainer",
            () => /** @type {any} */ (containerRef).el ?? null,
        );
    }

    const hotkeyService = useService("hotkey");
    const navigator = new Navigator(newOptions, hotkeyService);
    const observer = new MutationObserver(() => navigator.update());

    const onFocus = (/** @type {FocusEvent} */ { target }) =>
        navigator._checkFocus(/** @type {any} */ (target));
    useEffect(
        (containerEl) => {
            if (containerEl) {
                navigator.update();
                observer.observe(containerEl, {
                    childList: true,
                    subtree: true,
                });
                browser.addEventListener("focus", onFocus, true);
            }
            return () => {
                observer.disconnect();
                browser.removeEventListener("focus", onFocus, true);
            };
        },
        () => [/** @type {any} */ (containerRef).el],
    );
    onWillDestroy(() => navigator._destroy());

    return navigator;
}

/**
 * @param {Navigator | undefined} navigator
 * @param {() => HTMLElement | null | undefined} elGetter
 * @returns {{ readonly isActive: boolean }}
 */
export function useNavigatorActive(navigator, elGetter) {
    if (!navigator) {
        return { isActive: false };
    }
    const state = useState(navigator.state);
    return {
        get isActive() {
            void state.itemsRevision;
            const activeEl = state.activeItemEl;
            if (activeEl === null || activeEl === undefined) {
                return false;
            }
            return activeEl === elGetter();
        },
    };
}
