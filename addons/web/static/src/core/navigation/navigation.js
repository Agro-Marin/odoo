// @ts-check
/** @odoo-module native */

/** @module @web/core/navigation/navigation */

import { onWillDestroy, reactive, useEffect, useRef } from "@odoo/owl";
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
        this.target.addEventListener("focus", onFocus);

        if (this._options.mouseActivation === "armed") {
            // Armed hover: the pointer only speaks once it has moved since the
            // last keyboard action (see Navigator._rearmMouse). Activation
            // rides mouseenter/mouseleave on the hover surface, which may be a
            // larger element than the item itself -- a list row around the
            // anchor that carries the item's identity.
            const hoverTarget = this._options.getHoverTarget?.(el) ?? this.target;
            const onMouseEnter = () => this._onArmedMouseEnter();
            const onMouseLeave = () => this._onArmedMouseLeave();
            hoverTarget.addEventListener("mouseenter", onMouseEnter);
            hoverTarget.addEventListener("mouseleave", onMouseLeave);
            this._removeListeners = () => {
                this.target.removeEventListener("focus", onFocus);
                hoverTarget.removeEventListener("mouseenter", onMouseEnter);
                hoverTarget.removeEventListener("mouseleave", onMouseLeave);
            };
        } else {
            const onMouseMove = () => this._onMouseMove();
            this.target.addEventListener("mousemove", onMouseMove);
            this._removeListeners = () => {
                this.target.removeEventListener("focus", onFocus);
                this.target.removeEventListener("mousemove", onMouseMove);
            };
        }
    }

    select() {
        this.setActive();
        this.target.click();
    }

    setActive(focus = true) {
        scrollTo(this.target);
        this._navigator._setActiveItem(this.index);
        this.target.classList.add(this._options.activeClass);
        this._setAriaSelected("true");

        if (focus && !this._options.virtualFocus) {
            this._navigator._throttledFocus.cancel();
            this._navigator._throttledFocus(this.target);
        }
    }

    setInactive(blur = true) {
        this.target.classList.remove(this._options.activeClass);
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

    /**
     * @private
     */
    _onArmedMouseEnter() {
        if (
            this._navigator.isMouseArmed &&
            this._navigator.activeItem !== this &&
            this._navigator._isNavigationAvailable(this.target)
        ) {
            this.setActive(false);
            this._options.onMouseEnter?.(this);
        }
    }

    /**
     * The pointer walking off an item withdraws the highlight; a mouseleave
     * the pointer did not cause -- the list re-rendering or moving under a
     * still cursor -- must not, which is exactly what the arming gate keeps
     * out.
     *
     * @private
     */
    _onArmedMouseLeave() {
        if (this._navigator.isMouseArmed) {
            this._navigator.clearActiveItem();
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

        // An option declared as an accessor keeps answering for this
        // navigator's life; `mergeNavigationOptions` is the only combinator
        // that does not flatten it into the value it happened to hold.
        /** @private */
        this._options = mergeNavigationOptions(this._makeDefaultOptions(), options);

        /**
         * @private
         * @type {boolean}
         */
        this._mouseArmed = false;
        /**
         * @private
         * @type {(() => void) | null}
         */
        this._disarmMouse = null;
        this._rearmMouse();

        if (this._options.shouldRegisterHotkeys) {
            this.registerHotkeys();
        }
    }

    /**
     * @private
     * @returns {NavigationOptions}
     */
    _makeDefaultOptions() {
        return {
            // Two callers share this predicate and hand it different targets.
            // On the hotkey path `target` is the *focused* element; with a
            // virtual focus the real focus never sits on an item -- that is
            // the whole point of the mode -- so `contains(target)` can only
            // ever say no there, and the old `contains && (isFocused ||
            // virtualFocus)` shape made the `virtualFocus` disjunct
            // unreachable for the keyboard. On the mouse-move path `target`
            // is the hovered item itself, where `contains` is the right
            // question. Hence the split: an item target follows the focused
            // rule, and a virtual-focus navigator additionally answers yes
            // while the real focus is anywhere in its container -- the
            // element its virtual cursor works on behalf of.
            isNavigationAvailable: (
                /** @type {{ navigator: Navigator, target: HTMLElement }} */ { target },
            ) => {
                if (this.contains(target)) {
                    return this.isFocused || this._options.virtualFocus;
                }
                return Boolean(
                    this._options.virtualFocus &&
                    this._options.getContainer?.()?.contains(target),
                );
            },
            activeClass: ACTIVE_ELEMENT_CLASS,
            mouseActivation: "movement",
            shouldFocusChildInput: true,
            shouldFocusFirstItem: false,
            shouldRegisterHotkeys: true,
            virtualFocus: false,
            wrap: true,
            hotkeys: {
                home: () => this.activateFirst(),
                end: () => this.activateLast(),
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

    /**
     * @type {boolean} whether hover activation is currently armed; always
     *  false outside `mouseActivation: "armed"`. See `_rearmMouse`.
     */
    get isMouseArmed() {
        return this._mouseArmed;
    }

    next() {
        this._rearmMouse();
        if (!this.hasActiveItem) {
            this.items[0]?.setActive();
        } else if (
            this.activeItemIndex + 1 >= this.items.length &&
            !this._options.wrap
        ) {
            // Stepping past the end clears the cursor; the next step in the
            // same direction re-enters from the opposite end (the no-active
            // branch above).
            this.clearActiveItem();
        } else {
            this.items[(this.activeItemIndex + 1) % this.items.length]?.setActive();
        }
    }

    previous() {
        this._rearmMouse();
        const hasActive = this.hasActiveItem;
        const index = this.activeItemIndex - 1;
        if (!hasActive) {
            this.items.at(-1)?.setActive();
        } else if (index < 0) {
            if (this._options.wrap) {
                this.items.at(-1)?.setActive();
            } else {
                // Symmetric to next(): past the start the cursor clears, and
                // another step back re-enters from the last item.
                this.clearActiveItem();
            }
        } else {
            this.items[index]?.setActive();
        }
    }

    /**
     * Activates the first item -- the entry point a consumer uses when a
     * freshly (re)built list should present its first choice. With no items
     * the active cursor is cleared instead. Re-arms hover activation like a
     * keyboard step does: entering a list is a navigation act.
     */
    activateFirst() {
        this._rearmMouse();
        if (this.items.length) {
            this.items[0].setActive();
        } else {
            this.clearActiveItem();
        }
    }

    /**
     * Symmetric to `activateFirst`: enter the list from its far end, e.g. when
     * an ArrowUp is what opened it.
     */
    activateLast() {
        this._rearmMouse();
        if (this.items.length) {
            this.items.at(-1).setActive();
        } else {
            this.clearActiveItem();
        }
    }

    /**
     * Leaves no item active. The real focus is left where it is: with
     * `virtualFocus` there is nothing to blur, and without it the caller is
     * saying "no current choice", not "drop the keyboard".
     */
    clearActiveItem() {
        this._setActiveItem(-1);
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

    /**
     * Arms hover activation only once the pointer has actually moved again.
     *
     * In `mouseActivation: "armed"` a mouseenter or mouseleave may activate or
     * clear an item only if a real mousemove happened since the last keyboard
     * action -- otherwise a list rendered or repositioned under a still cursor
     * would steal the highlight from the keyboard. Every navigation act
     * (next/previous/activateFirst/activateLast) disarms and waits for the
     * next window-level mousemove. A no-op in the default "movement" mode,
     * where activation is keyed on the item's own mousemove and needs no
     * memory.
     *
     * @private
     */
    _rearmMouse() {
        if (this._options.mouseActivation !== "armed") {
            return;
        }
        this._mouseArmed = false;
        this._disarmMouse?.();
        const arm = () => {
            this._mouseArmed = true;
            this._disarmMouse = null;
        };
        browser.addEventListener("mousemove", arm, { capture: true, once: true });
        this._disarmMouse = () =>
            browser.removeEventListener("mousemove", arm, { capture: true });
    }

    _destroy() {
        this._throttledFocus.cancel();
        this._disarmMouse?.();
        this._disarmMouse = null;
        this._mouseArmed = false;
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
 * `mergeNavigationOptions`, which is what carries the accessors across the
 * merge that would otherwise flatten them into values.
 *
 * @typedef {Object} NavigationOptions
 * @property {() => HTMLElement[]} [getItems]
 * @property {() => HTMLElement | null} [getContainer]
 * @property {(info: { navigator: Navigator, target: HTMLElement }) => boolean} [isNavigationAvailable]
 * @property {Record<string, any>} [hotkeys]
 * @property {Function} [onUpdated]
 * @property {Function} [onItemActivated]
 * @property {Function} [onMouseEnter]
 * @property {string} [activeClass] class carried by the active item's target
 *  (default: `"focus"`). A component whose stylesheet already speaks another
 *  dialect -- e.g. jQuery-UI's `ui-state-active` -- names it here instead of
 *  mirroring the cursor into its own state.
 * @property {"movement" | "armed"} [mouseActivation] how the pointer takes the
 *  cursor (default: `"movement"`). `"movement"`: any mousemove over an item
 *  activates it. `"armed"`: mouseenter activates and mouseleave clears, but
 *  only once the pointer has really moved since the last keyboard action --
 *  the combobox convention, where a list opening under a still cursor must
 *  not steal the highlight the keyboard just placed.
 * @property {(el: HTMLElement) => HTMLElement} [getHoverTarget] the element
 *  whose enter/leave events speak for an item in `"armed"` mode, when that
 *  surface is larger than the item element itself (e.g. the list row around
 *  the anchor). Defaults to the item's own target.
 * @property {boolean} [virtualFocus]
 * @property {boolean} [shouldFocusChildInput]
 * @property {boolean} [shouldFocusFirstItem]
 * @property {boolean} [shouldRegisterHotkeys]
 * @property {boolean} [wrap] whether next() on the last item and previous() on
 *  the first wrap around (default: true). With `wrap: false` stepping past
 *  either end clears the active item, and the following step in the same
 *  direction re-enters the list from the opposite end.
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
 * Combine option sources, later winning over earlier, **without flattening
 * accessors**.
 *
 * Copying an object -- by spread, by `deepMerge`, by anything that reads a key
 * and writes its value -- turns a getter into whatever it returned at that
 * moment. Restoring the accessors afterwards is what lets an option follow
 * something that moves rather than freezing at setup, and it has to happen at
 * *every* place options are copied. When that rule lived in a comment rather
 * than in the API, `Dropdown`, the component that actually
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
