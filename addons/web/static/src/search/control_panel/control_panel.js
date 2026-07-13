// @ts-check
/** @odoo-module native */

/** @module @web/search/control_panel/control_panel - Control panel UI with search bar, breadcrumbs, filter/groupby menus, and embedded actions */

import { Component, onMounted, useEffect, useRef, useState } from "@odoo/owl";
import { CheckBox } from "@web/components/checkbox/checkbox";
import { AccordionItem } from "@web/components/dropdown/accordion_item";
import { Dropdown } from "@web/components/dropdown/dropdown";
import { useDropdownState } from "@web/components/dropdown/dropdown_hooks";
import { DropdownItem } from "@web/components/dropdown/dropdown_item";
import { Pager } from "@web/components/pager/pager";
import { browser } from "@web/core/browser/browser";
import { getActiveHotkey } from "@web/core/browser/hotkeys";
import { SearchModelEvent } from "@web/core/events";
import { _t } from "@web/core/l10n/translation";
import { useChildRef, useService } from "@web/core/utils/hooks";
import { Breadcrumbs } from "@web/search/breadcrumbs/breadcrumbs";
import {
    EmbeddedActionsBar,
    useEmbeddedActions,
} from "@web/search/embedded_actions_bar/embedded_actions_bar";
import { SearchBar } from "@web/search/search_bar/search_bar";
import { useCommand } from "@web/services/commands/command_hook";
import { useHotkey } from "@web/services/hotkeys/hotkey_hook";

const STICKY_CLASS = "o_mobile_sticky";

/**
 * Default embedded infos so templates can safely read `state.embeddedInfos.*`
 * when the action has no embedded actions. A factory, not a shared constant:
 * shared nested arrays get aliased by every `{ ...CONST }` shallow copy, so a
 * stray push would leak across control-panel instances.
 *
 * @returns {{showEmbedded: boolean, embeddedActions: any[], visibleEmbeddedActions: any[], newActionIsShared: boolean, newActionName: string, currentEmbeddedAction: any}}
 */
function makeNoEmbeddedInfos() {
    return {
        showEmbedded: false,
        embeddedActions: [],
        visibleEmbeddedActions: [],
        newActionIsShared: false,
        newActionName: "",
        currentEmbeddedAction: undefined,
    };
}

/**
 * Main control panel component that renders breadcrumbs, search bar, view
 * switcher, pager, embedded actions tabs, and layout action buttons.
 *
 * Handles mobile sticky scroll behavior and keyboard navigation. The
 * embedded-actions machinery lives in the {@link EmbeddedActions} model and
 * the {@link EmbeddedActionsBar} sub-component, and is only instantiated
 * when the current action provides embedded actions; the thin delegating
 * methods kept here are the extension surface for inheriting control panels
 * (and back the mobile `web.embeddedActionsDropdown` render).
 */
export class ControlPanel extends Component {
    static template = "web.ControlPanel";
    static components = {
        Pager,
        SearchBar,
        Dropdown,
        DropdownItem,
        Breadcrumbs,
        AccordionItem,
        CheckBox,
        EmbeddedActionsBar,
    };
    static props = {
        display: { type: Object, optional: true },
        slots: { type: Object, optional: true },
    };

    // Declared with @type so strictNullChecks treats them as initialized; real
    // assignment happens in setup()/lifecycle hooks (OWL components have no constructor).
    /** @type {any} */
    actionService;
    /** @type {any} */
    pagerProps;
    /** @type {any} */
    notificationService;
    /** @type {any[]} */
    breadcrumbs;
    /** @type {any} */
    orm;
    /** @type {import("@web/search/embedded_actions_bar/embedded_actions_bar").EmbeddedActions | null} */
    embeddedActions;
    /** @type {import("@web/components/dropdown/dropdown_hooks").DropdownState} */
    embeddedActionsDropdown;
    /** @type {{el: HTMLElement | null}} */
    root;
    /** @type {{el: HTMLElement | null}} */
    newActionNameRef;
    /** @type {any} */
    adaptiveMenuRef;
    /** @type {{embeddedInfos: {showEmbedded: boolean, embeddedActions: any[], newActionIsShared: boolean, newActionName: string, visibleEmbeddedActions: any[], currentEmbeddedAction: any}}} */
    state;
    /** @type {(ev: Event) => void} */
    onScrollThrottledBound;
    /** @type {number} */
    scrollingElementHeight;
    /** @type {number} */
    oldScrollTop;
    /** @type {number} */
    lastScrollTop;
    /** @type {number} */
    initialScrollTop;
    /** @type {boolean} */
    isScrolling;

    setup() {
        this.actionService = useService("action");
        this.pagerProps = this.env.config.pagerProps
            ? useState(this.env.config.pagerProps)
            : undefined;
        this.notificationService = useService("notification");
        this.breadcrumbs = useState(this.env.config.breadcrumbs);
        // Kept although unused here: inheriting control panels rely on it
        // (e.g. account_accountant's BankRecKanbanControlPanel).
        this.orm = useService("orm");

        this.root = useRef("root");
        this.adaptiveMenuRef = useChildRef();

        // `null` when the current action has no embedded actions: the bar is
        // not rendered and none of the embedded machinery is instantiated.
        this.embeddedActions = useEmbeddedActions();
        // Shared with the `web.embeddedActionsDropdown` template rendered on
        // mobile from this component (desktop renders it in the bar).
        this.embeddedActionsDropdown = useDropdownState();
        this.newActionNameRef = useRef("newActionNameRef");
        this.state = useState({
            embeddedInfos: this.embeddedActions
                ? this.embeddedActions.embeddedInfos
                : makeNoEmbeddedInfos(),
        });

        this.onScrollThrottledBound = this.onScrollThrottled.bind(this);

        const { viewSwitcherEntries } = this.env.config;
        for (const view of viewSwitcherEntries || []) {
            useCommand(
                _t("Show %s view", view.name),
                () => {
                    this.switchView(view.type);
                },
                {
                    category: "view_switcher",
                    // Global so the command is available regardless of which
                    // UI element has focus (ControlPanel doesn't register as
                    // an activeElement). The isAvailable guard ensures only
                    // non-current view types are shown.
                    global: true,
                    isAvailable: () => view.type !== this.env.config.viewType,
                },
            );
        }

        if (viewSwitcherEntries?.length > 1) {
            useHotkey(
                "alt+shift+v",
                () => {
                    this.cycleThroughViews();
                },
                {
                    bypassEditableProtection: true,
                    withOverlay: () =>
                        this.root.el.querySelector("nav.o_cp_switch_buttons"),
                },
            );
        }

        useEffect(
            () => {
                if (
                    !this.env.isSmall ||
                    ("adaptToScroll" in this.display && !this.display.adaptToScroll)
                ) {
                    return;
                }
                const scrollingEl = this.getScrollingElement();
                const resizeObserver = new ResizeObserver((entries) => {
                    for (const entry of entries) {
                        const target = /** @type {any} */ (entry.target);
                        if (this.scrollingElementHeight !== target.scrollHeight) {
                            this.oldScrollTop +=
                                target.scrollHeight - this.scrollingElementHeight;
                            this.scrollingElementHeight = target.scrollHeight;
                        }
                    }
                });
                resizeObserver.observe(scrollingEl);
                scrollingEl.addEventListener("scroll", this.onScrollThrottledBound);
                this.root.el.style.top = "0px";
                this.scrollingElementHeight = scrollingEl.scrollHeight;
                return () => {
                    resizeObserver.disconnect();
                    scrollingEl.removeEventListener(
                        "scroll",
                        this.onScrollThrottledBound,
                    );
                };
                // Explicit deps: without them OWL defaults to `() => [NaN]` (NaN !== NaN),
                // re-running cleanup+setup on every patch. That would tear down and rebuild
                // the ResizeObserver/scroll listener on each re-render and, worse, reset
                // `root.el.style.top` to "0px" mid-scroll — snapping the sticky panel back
                // down and fighting the offset kept by onScrollThrottled. These inputs only
                // change on small/large switch, adaptToScroll toggle, or root remount.
            },
            () => [this.env.isSmall, this.display.adaptToScroll, this.root.el],
        );

        onMounted(() => {
            if (
                !this.env.isSmall ||
                ("adaptToScroll" in this.display && !this.display.adaptToScroll)
            ) {
                return;
            }
            this.oldScrollTop = 0;
            this.lastScrollTop = 0;
            this.initialScrollTop = this.getScrollingElement().scrollTop;
        });
    }

    /** @returns {HTMLElement} the scrollable parent element */
    getScrollingElement() {
        return this.root.el.parentElement;
    }

    /**
     * @returns {Object}
     */
    get display() {
        return {
            layoutActions: true,
            ...this.props.display,
        };
    }

    /**
     * @param {import("@web/search/embedded_actions_bar/embedded_actions_bar").EmbeddedAction} action
     * @returns {boolean}
     */
    _isEmbeddedActionVisible(action) {
        return this.state.embeddedInfos.visibleEmbeddedActions.includes(action.id);
    }

    /**
     * @param {import("@web/search/embedded_actions_bar/embedded_actions_bar").EmbeddedAction} action
     * @returns {string} CSS class ("selected" or "")
     */
    getDropdownClass(action) {
        return (!this.env.isSmall && this._isEmbeddedActionVisible(action)) ||
            (this.env.isSmall &&
                this.state.embeddedInfos.currentEmbeddedAction?.id === action.id)
            ? "selected"
            : "";
    }

    /** Show or hide the embedded actions bar. */
    async onClickShowEmbedded() {
        await this.embeddedActions.toggleBar();
    }

    /**
     * @param {import("@web/search/embedded_actions_bar/embedded_actions_bar").EmbeddedAction} action
     */
    async onEmbeddedActionClick(action) {
        return this.embeddedActions.openAction(action);
    }

    /**
     * @param {number|false} actionId
     */
    _setVisibility(actionId) {
        return this.embeddedActions.toggleActionVisibility(actionId);
    }

    /**
     * @param {import("@web/search/embedded_actions_bar/embedded_actions_bar").EmbeddedAction} action
     */
    openConfirmationDialog(action) {
        return this.embeddedActions.confirmDelete(action);
    }

    _onShareCheckboxChange() {
        this.state.embeddedInfos.newActionIsShared =
            !this.state.embeddedInfos.newActionIsShared;
    }

    /**
     * @param {Event} ev
     */
    async _saveNewAction(ev) {
        const saved = await this.embeddedActions.saveNewAction();
        if (!saved) {
            ev.stopPropagation();
            this.newActionNameRef.el?.focus();
        }
    }

    /**
     * Show or hide the control panel on the top screen; throttled to avoid
     * refreshing the scroll position more often than necessary.
     */
    onScrollThrottled() {
        if (this.isScrolling) {
            return;
        }
        this.isScrolling = true;
        browser.requestAnimationFrame(() => (this.isScrolling = false));

        const scrollTop = this.getScrollingElement().scrollTop;
        const delta = Math.round(scrollTop - this.oldScrollTop);

        if (scrollTop > this.initialScrollTop) {
            // Beneath initial position => sticky display
            this.root.el.classList.add(STICKY_CLASS);
            if (delta <= 0) {
                // Going up | not moving
                this.lastScrollTop = Math.min(0, this.lastScrollTop - delta);
            } else {
                // Going down
                this.lastScrollTop = Math.max(
                    -this.root.el.offsetHeight,
                    -this.root.el.offsetTop - delta,
                );
            }
            this.root.el.style.top = `${this.lastScrollTop}px`;
        } else {
            // Above initial position => standard display
            this.root.el.classList.remove(STICKY_CLASS);
            this.lastScrollTop = 0;
        }

        this.oldScrollTop = scrollTop;
    }

    /**
     * Switch from the current view to another, e.g. from the view switcher;
     * resets mobile search state.
     *
     * @param {import("@web/views/view").ViewType} viewType
     */
    switchView(viewType, newWindow) {
        return this.actionService.switchView(viewType, {}, { newWindow });
    }

    /** Cycle to the next view type in the view switcher. */
    cycleThroughViews() {
        const currentViewType = this.env.config.viewType;
        const viewSwitcherEntries = this.env.config.viewSwitcherEntries;
        const currentIndex = viewSwitcherEntries.findIndex(
            (entry) => entry.type === currentViewType,
        );
        const nextIndex = (currentIndex + 1) % viewSwitcherEntries.length;
        return this.switchView(viewSwitcherEntries[nextIndex].type);
    }

    /**
     * @param {KeyboardEvent} ev
     */
    onMainButtonsKeydown(ev) {
        const hotkey = getActiveHotkey(ev);
        if (hotkey === "arrowdown") {
            this.env.searchModel.trigger(SearchModelEvent.FOCUS_VIEW);
            ev.preventDefault();
            ev.stopPropagation();
        }
    }

    /** Convert button elements inside the adaptive dropdown into dropdown-item styling. */
    dropdownifyButtons() {
        const adaptiveMenu = this.adaptiveMenuRef.el;
        if (!adaptiveMenu) {
            return;
        }
        const meaningfulElements = this.getBoxedElements(adaptiveMenu.children);
        for (const el of meaningfulElements) {
            el.classList.add("dropdown-item");
            el.classList.remove("btn");
        }
    }

    /**
     * Recursively collect visible (non-`display:none`) elements, flattening
     * `display:contents` wrappers.
     * @param {HTMLCollection} elements
     * @returns {HTMLElement[]}
     */
    getBoxedElements(elements) {
        /** @type {HTMLElement[]} */
        const boxed = [];
        for (const el of [...elements]) {
            const elStyles = el.ownerDocument.defaultView.getComputedStyle(el);
            if (elStyles.getPropertyValue("display") === "contents") {
                boxed.push(...this.getBoxedElements(el.children));
            } else if (elStyles.getPropertyValue("display") === "none") {
                continue;
            } else {
                // ``elements`` is an HTMLCollection typed as ``Element``, but at
                // runtime it's always an HTMLElement (Bootstrap toolbar markup).
                boxed.push(/** @type {HTMLElement} */ (el));
            }
        }
        return boxed;
    }
}
