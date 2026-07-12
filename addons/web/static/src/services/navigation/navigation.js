// @ts-check
/** @odoo-module native */

/** @module @web/services/navigation/navigation - Keyboard arrow-key navigation hook for selectable item lists */

import { onWillDestroy, reactive, useEffect, useRef, useState } from "@odoo/owl";
import { browser } from "@web/core/browser/browser";
import { deepMerge } from "@web/core/utils/collections/objects";
import { scrollTo } from "@web/core/utils/dom/scrolling";
import { useService } from "@web/core/utils/hooks";
import { throttleForAnimation } from "@web/core/utils/timing";
export const ACTIVE_ELEMENT_CLASS = "focus";

class NavigationItem {
    /**@type {number} */
    index = -1;

    /**
     * The container element
     * @type {HTMLElement}
     */
    el = undefined;

    /**
     * The actual "clicked" element, it can be the same
     * as @see el but will be the closest child input if
     * options.shouldFocusChildInput is true
     * @type {HTMLElement}
     */
    target = undefined;

    /**
     * @param {{ index: number, el: HTMLElement, options: NavigationOptions, navigator: Navigator }} param0
     */
    constructor({ index, el, options, navigator }) {
        this.index = index;

        /**@private */
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

        if (this.el.ariaSelected !== "true") {
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
        this.target.ariaSelected = "true";

        if (focus && !this._options.virtualFocus) {
            this._navigator._throttledFocus.cancel();
            this._navigator._throttledFocus(this.target);
        }
    }

    setInactive(blur = true) {
        this.target.classList.remove(ACTIVE_ELEMENT_CLASS);
        this.target.ariaSelected = "false";
        if (blur && !this._options.virtualFocus) {
            this.target.blur();
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
    /**@type {Array<NavigationItem>}*/
    items = [];

    /**@private @type {Array<() => void>}*/ _hotkeyRemoves = [];
    /**@private @type {import("@web/services/hotkeys/hotkey_service").HotkeyService}*/ _hotkeyService =
        undefined;

    /**
     * @param {NavigationOptions} options
     * @param {import("@web/services/hotkeys/hotkey_service").HotkeyService} hotkeyService
     */
    constructor(options, hotkeyService) {
        this._hotkeyService = hotkeyService;
        // Per-instance (not module-level): stacked navigators (e.g. nested
        // overlays) must not cancel each other's pending focus.
        /**@private*/
        this._throttledFocus = throttleForAnimation((/** @type {HTMLElement} */ el) =>
            el?.focus(),
        );
        // Reactive state lets OWL consumers (via useNavigatorActive) bind the
        // focus class declaratively (`t-att-class`), fixing races where a
        // parent re-render wipes the imperative `classList` write below.
        // Imperative writes stay for backward compat with non-OWL/CSS-only
        // consumers; both are kept in lockstep through the setters.
        this.state = reactive({
            /**@type {number}*/
            activeItemIndex: -1,
            /**@type {HTMLElement | null}*/
            activeItemEl: null,
            /**Bumped whenever {@link items} is rebuilt.*/
            itemsRevision: 0,
        });

        /**@private*/
        this._options = deepMerge(
            {
                isNavigationAvailable: (
                    /** @type {{ navigator: Navigator, target: HTMLElement }} */ {
                        target,
                    },
                ) =>
                    this.contains(target) &&
                    (this.isFocused || this._options.virtualFocus),
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
            },
            options,
        );

        if (this._options.shouldRegisterHotkeys) {
            this.registerHotkeys();
        }
    }

    // ---- Reactive-backed accessors ----
    //
    // These preserve the public API (`navigator.activeItem`,
    // `navigator.activeItemIndex`) while persisting the values inside the
    // reactive `state` object so OWL subscribers see every change.

    /**@type {number}*/
    get activeItemIndex() {
        return this.state.activeItemIndex;
    }
    set activeItemIndex(value) {
        this.state.activeItemIndex = value;
    }

    /**@type {NavigationItem | null}*/
    get activeItem() {
        const idx = this.state.activeItemIndex;
        return idx >= 0 ? (this.items[idx] ?? null) : null;
    }
    set activeItem(item) {
        // Store the element rather than the NavigationItem wrapper so
        // consumers can match against a known DOM reference without
        // depending on the internal NavigationItem identity (which gets
        // rebuilt on every `update()`).
        this.state.activeItemEl = item?.el ?? null;
    }

    /**
     * Returns true if the current active item is not null and still inside the DOM
     * @type {boolean}
     */
    get hasActiveItem() {
        return Boolean(this.activeItem?.el.isConnected);
    }

    /**
     * Returns true if the focus is on any of the navigable items
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
            this.items[index % this.items.length]?.setActive();
        }
    }

    update() {
        const oldItems = new Map(this.items.map((item) => [item.el, item]));
        const oldActiveItem = this.activeItem;
        // Whether the reconcile below may follow the active item with real DOM
        // focus. Reconciling after a DOM mutation (e.g. a hover-activated item
        // was removed) must NOT pull focus into the menu when the user's focus
        // is legitimately elsewhere (a search input, a form field). It is
        // allowed both when focus is already inside the menu AND when focus has
        // been lost entirely (activeElement is <body>/null — typically because
        // the previously focused item was just removed from the DOM, e.g. the
        // Confirm/Reset buttons collapsing): there is no external element to
        // preserve, so the active item should regain focus.
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
                // Focus is already on this item — focusing is a no-op, so allow.
                this._updateActiveItemIndex(focusedElementIndex, true);
            } else {
                this._updateActiveItemIndex(-1, focusWasInMenu);
            }

            this._options.onUpdated?.(this);

            if (this._options.shouldFocusFirstItem) {
                this.items[0]?.setActive();
            }
            // Wake subscribers deriving from the items list (e.g.
            // useNavigatorActive) via a monotonic counter, since reactive
            // primitives only notify on reassignment and reassigning
            // `this.items` would force unnecessary re-renders.
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
        this.unregisterHotkeys();
    }

    /**
     * @param {number} index
     */
    _setActiveItem(index) {
        this.activeItem?.setInactive(false);
        this.activeItemIndex = index;
        if (index >= 0) {
            this.activeItem = this.items[index];
            this._options.onItemActivated?.(this.activeItem.el);
        } else {
            this.activeItem = null;
        }
    }

    /**
     * True when ``el`` is the currently-active navigable item. Reads through
     * the reactive `state` so callers wrapped in `useState(navigator.state)`
     * re-render on change. Used internally by {@link useNavigatorActive}.
     *
     * @param {HTMLElement | undefined | null} el
     * @returns {boolean}
     */
    isActiveEl(el) {
        return Boolean(el) && this.state.activeItemEl === el;
    }

    /**
     * @private
     * @param {number} index
     * @param {boolean} [mayFocus=true] When false, the item is activated
     *   visually only — DOM focus stays where it is. Used by ``update()`` to
     *   avoid stealing focus into the menu on a reconcile when the user's focus
     *   is legitimately outside it.
     */
    _updateActiveItemIndex(index, mayFocus = true) {
        if (this.items[index]) {
            const shouldFocus =
                mayFocus &&
                !this.items.some((item) => item.target === document.activeElement);
            this.items[index].setActive(shouldFocus);
        } else {
            // Route through _setActiveItem for a consistent transition
            // (setInactive + single index-change path). Direct mutation of
            // ``activeItemIndex`` here previously caused a "stuck on item 1" bug.
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
 * @typedef {Object} NavigationOptions
 * @property {() => HTMLElement[]} [getItems]
 * @property {(info: { navigator: Navigator, target: HTMLElement }) => boolean} [isNavigationAvailable]
 * @property {Record<string, any>} [hotkeys]
 * @property {Function} [onUpdated]
 * @property {Function} [onItemActivated]
 * @property {Function} [onMouseEnter]
 * @property {boolean} [virtualFocus] - If true, items are only visually
 * focused so the actual focus can be kept on another input.
 * @property {boolean} [shouldFocusChildInput] - If true, elements like inputs or buttons
 * inside of the items are focused instead of the items themselves.
 * @property {boolean} [shouldFocusFirstItem] - If true, the first item is auto-focused.
 * @property {boolean} [shouldRegisterHotkeys] - If true, registers all hotkeys directly when
 * the hook is called.
 */

/**
 * @typedef {Object} HotkeyOptions
 * @property {hotkeyHandler} callback
 * @property {(info: { navigator: Navigator, target: HTMLElement }) => boolean} [isAvailable]
 * @property {boolean} [bypassEditableProtection]
 * @property {boolean} [allowRepeat]
 */

/**
 * Callback used to override the behaviour of a specific
 * key input.
 *
 * @callback hotkeyHandler
 * @param {Navigator} navigator
 */

/**
 * This hook adds keyboard navigation to items contained in an element.
 * It's purpose is to improve navigation in constrained context such
 * as dropdown and menus.
 *
 * This hook also has the following features:
 * - Hotkeys override and customization
 * - Navigation between inputs elements
 * - Optional virtual focus
 * - Focus on mouse enter
 *
 * @param {string|Object} containerRef
 * @param {NavigationOptions} options
 * @returns {Navigator}
 */
export function useNavigation(containerRef, options = {}) {
    containerRef =
        typeof containerRef === "string" ? useRef(containerRef) : containerRef;

    const newOptions = { ...options };
    if (!newOptions.getItems) {
        newOptions.getItems = () =>
            /** @type {any} */ (containerRef).el?.querySelectorAll(
                ":scope .o-navigable",
            ) ?? [];
    }

    const hotkeyService = useService("hotkey");
    const navigator = new Navigator(newOptions, hotkeyService);
    const observer = new MutationObserver(() => navigator.update());

    // Scoped to the container's lifetime (dropdown open), like the hotkey
    // registrations: list/kanban pages mount one Navigator per card menu, so
    // a closed dropdown must not leave a capture listener on every focus event.
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
    // onWillDestroy (not onWillUnmount): unmount hooks don't fire for
    // components destroyed before mount, which would leak the hotkey
    // registrations and item listeners.
    onWillDestroy(() => navigator._destroy());

    return navigator;
}

/**
 * Subscribe an OWL component to a navigator's active-item state.
 *
 * Returns an object whose ``isActive`` getter is OWL-reactive: any template
 * reading it re-renders when ``elGetter()`` becomes (or stops being) the
 * navigator's active element. Use when focus styling must be co-managed by
 * OWL (``t-att-class``) — the declarative path survives parent re-renders
 * that would otherwise wipe the imperative ``classList.add("focus")`` in
 * {@link NavigationItem.setActive}.
 *
 * Example — DropdownItem template:
 * ```xml
 * <span t-att-class="{ focus: nav.isActive }">…</span>
 * ```
 * setup:
 * ```js
 * this.itemRef = useRef("root");
 * this.nav = useNavigatorActive(this.env.navigation, () => this.itemRef.el);
 * ```
 *
 * Opt-in: consumers that skip it keep relying on ``NavigationItem``'s
 * imperative class management — this refactor is additive.
 *
 * @param {Navigator | undefined} navigator
 * @param {() => HTMLElement | null | undefined} elGetter
 * @returns {{ readonly isActive: boolean }}
 */
export function useNavigatorActive(navigator, elGetter) {
    if (!navigator) {
        // No navigator (e.g. component used outside a navigable container)
        // — return a stable, non-reactive stub so callers can still bind
        // safely.  Avoids forcing every consumer to add a null check.
        return { isActive: false };
    }
    const state = useState(navigator.state);
    return {
        get isActive() {
            // Read both ``activeItemEl`` (changes each transition) and
            // ``itemsRevision`` (changes when items[] rebuilds, e.g. same
            // element removed/re-added) to register with OWL's reactive proxy.
            void state.itemsRevision;
            const activeEl = state.activeItemEl;
            // Short-circuit when no item is active — otherwise the first
            // render (before any selection) would compute ``null === null``
            // as true for every consumer, applying focus to all items and
            // desyncing the OWL diff from the true active item.
            if (activeEl === null || activeEl === undefined) {
                return false;
            }
            return activeEl === elGetter();
        },
    };
}
