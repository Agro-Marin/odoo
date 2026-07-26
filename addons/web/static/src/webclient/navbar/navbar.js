// @ts-check
/** @odoo-module native */

/** @module @web/webclient/navbar/navbar - Main navigation bar with app switcher, sub-menus, systray items, and mobile sidebar */

import {
    Component,
    onWillDestroy,
    useEffect,
    useExternalListener,
    useRef,
    useState,
} from "@odoo/owl";
import { Dropdown } from "@web/components/dropdown/dropdown";
import { DropdownGroup } from "@web/components/dropdown/dropdown_group";
import { DropdownItem } from "@web/components/dropdown/dropdown_item";
import { Transition } from "@web/components/transition";
import { AppEvent } from "@web/core/events";
import { registry } from "@web/core/registry";
import { ErrorHandler } from "@web/core/utils/components";
import { useService } from "@web/core/utils/hooks";
import { debounce } from "@web/core/utils/timing";
const systrayRegistry = registry.category("systray");

// Schema for systray items. Consumers (this navbar's template) read
// `Component`, `props`, and `isDisplayed`; everything else is forwarded.
systrayRegistry.addValidation({
    Component: { validate: (c) => c?.prototype instanceof Component },
    props: { type: Object, optional: true },
    isDisplayed: { type: Function, optional: true },
    "*": true,
});

const getBoundingClientRect = Element.prototype.getBoundingClientRect;

const SWIPE_ACTIVATION_THRESHOLD = 100;

/** Dropdown subclass for navbar sub-menus (enables enterprise/website patching). */
export class MenuDropdown extends Dropdown {}

/**
 * Main navigation bar at the top of the webclient.
 *
 * Renders the app switcher, current app's sub-menus (with overflow "More" menu),
 * systray items, and mobile sidebar. Adapts to viewport width via a resize observer.
 */
export class NavBar extends Component {
    static template = "web.NavBar";
    static components = {
        Dropdown,
        DropdownItem,
        DropdownGroup,
        MenuDropdown,
        ErrorHandler,
        Transition,
    };
    static props = {};

    setup() {
        this.currentAppSectionsExtra = [];
        // Keys of systray items whose component threw during render, so the
        // getter can filter them out permanently. `handleItemError` used to
        // mutate a per-render COPY of the item (systrayItems rebuilds fresh
        // objects each render), so the faulty item remounted and re-threw —
        // and re-queued an error dialog — on every navbar re-render.
        this.failedSystrayKeys = new Set();
        this.actionService = useService("action");
        this.menuService = useService("menu");
        this.pwa = useService(/** @type {any} */ ("pwa"));
        this.root = useRef("root");
        this.appSubMenus = useRef("appSubMenus");
        const debouncedAdapt = debounce(this.adapt.bind(this), 250);
        onWillDestroy(() => debouncedAdapt.cancel());
        useExternalListener(window, "resize", debouncedAdapt);

        let adaptCounter = 0;
        const renderAndAdapt = () => {
            adaptCounter++;
            this.render();
        };

        systrayRegistry.addEventListener("UPDATE", renderAndAdapt);
        this.env.bus.addEventListener(AppEvent.MENUS_APP_CHANGED, renderAndAdapt);

        // onWillDestroy (not onWillUnmount): unmount hooks don't fire for
        // components destroyed before mount, which would leak the listeners.
        onWillDestroy(() => {
            systrayRegistry.removeEventListener("UPDATE", renderAndAdapt);
            this.env.bus.removeEventListener(
                AppEvent.MENUS_APP_CHANGED,
                renderAndAdapt,
            );
        });

        // Adapt only when menus or systrays changed, not on every patch.
        useEffect(
            () => {
                this.adapt();
            },
            () => [adaptCounter],
        );

        this.state = useState({
            isAllAppsMenuOpened: false,
            isAppMenuSidebarOpened: false,
        });
    }

    /**
     * @param {Error} error
     * @param {Object} item - the systray item that errored
     */
    handleItemError(error, item) {
        // Record the failing item's stable registry key (not the transient
        // per-render copy) so systrayItems drops it on every subsequent
        // render — otherwise it remounts and re-throws on the next navbar
        // re-render (app switch, systray UPDATE, overflow adapt), one error
        // dialog per render.
        this.failedSystrayKeys.add(item.key);
        // Uses Promise.resolve().then() (not queueMicrotask) so the error routes
        // through the unhandledrejection handler → UncaughtPromiseError dialog.
        Promise.resolve().then(() => {
            throw error;
        });
    }

    /** @returns {Object | undefined} the currently active app menu item */
    get currentApp() {
        return this.menuService.getCurrentApp();
    }

    /** @returns {Object[]} sub-menu tree nodes for the current app */
    get currentAppSections() {
        return (
            (this.currentApp &&
                this.menuService.getMenuAsTree(this.currentApp.id).childrenTree) ||
            []
        );
    }

    // Load-bearing no-op setter — NOT redundant with the getter above.
    //
    // ``website`` overrides this accessor with ``patch(NavBar.prototype, {get
    // currentAppSections() {...}})``. A POJO declaring only a getter produces
    // the descriptor ``{get, set: undefined}``, which ``Object.defineProperty``
    // would install verbatim, wiping any setter the target had.
    // ``core/utils/patch.js`` guards that ("get/set are defined together"): when
    // an extension supplies only one half it inherits the other from the
    // ancestor descriptor. But inheritance can only propagate a setter that
    // exists SOMEWHERE in the chain — this is that source. Drop it and the
    // property becomes getter-only for every patcher downstream, so any
    // ``this.currentAppSections = ...`` throws in strict mode.
    //
    // No such assignment exists today anywhere in odoo/addons or enterprise
    // (checked 2026-07-25), so this is insurance rather than an active fix —
    // but its absence is invisible to the test suite, precisely because nothing
    // assigns. Retire both setters together, and only with a grep over the
    // deployed addons, not on the strength of a green run.
    set currentAppSections(_) {}

    get isScopedApp() {
        return this.pwa.isScopedApp;
    }

    /** @returns {Object[]} visible systray items in display order */
    get systrayItems() {
        return systrayRegistry
            .getEntries()
            .filter(([key]) => !this.failedSystrayKeys.has(key))
            .map(([key, value]) => ({ key, ...value }))
            .filter((item) =>
                "isDisplayed" in item
                    ? item.isDisplayed(
                          /** @type {import("@web/env").OdooEnv} */ (this.env),
                      )
                    : true,
            )
            .reverse();
    }

    // Load-bearing no-op setter — see the note on ``set currentAppSections``.
    // ``website`` patches this accessor with a getter-only extension too.
    set systrayItems(_) {}

    /**
     * Compute the available width for app sections; if they overflow, move
     * the minimum needed sections into a "more" menu.
     *
     * NB: requires an upfront render to measure section widths, and may
     * trigger another render afterward depending on the outcome.
     */
    async adapt() {
        if (!this.root.el) {
            /** @todo do we still need this check? */
            // 'render' resolves after the render finishes even if the
            // component was destroyed meanwhile, so this.el may be unset.
            return;
        }

        // ------- Initialize -------
        const sectionsMenu = this.appSubMenus.el;
        if (!sectionsMenu) {
            // No need to continue adaptations if there is no sections menu.
            return;
        }

        // Save initial state to further check if new render has to be done.
        const initialAppSectionsExtra = this.currentAppSectionsExtra;
        const firstInitialAppSectionExtra = [...initialAppSectionsExtra].shift();
        const initialAppId = firstInitialAppSectionExtra?.appID;

        // Restore (needed to get offset widths)
        const sections = [
            ...sectionsMenu.querySelectorAll(":scope > *:not(.o_menu_sections_more)"),
        ];
        for (const section of sections) {
            section.classList.remove("d-none");
        }
        this.currentAppSectionsExtra = [];

        // ------- Check overflowing sections -------
        // Measure everything once (getBoundingClientRect, not offsetWidth,
        // avoids rounding errors), then run the overflow arithmetic and the
        // class mutations on the cached widths: interleaving reads with the
        // d-none writes would force one synchronous reflow per iteration.
        const sectionsAvailableWidth = getBoundingClientRect.call(sectionsMenu).width;
        const sectionWidths = sections.map((s) => getBoundingClientRect.call(s).width);
        const sectionsTotalWidth = sectionWidths.reduce((sum, w) => sum + w, 0);
        if (sectionsAvailableWidth < sectionsTotalWidth) {
            // Sections are overflowing
            // Initial width is harcoded to the width the more menu dropdown will take
            let width = 46;
            for (const [index] of sections.entries()) {
                if (sectionsAvailableWidth < width + sectionWidths[index]) {
                    // Last sections are overflowing
                    const overflowingSections = sections.slice(index);
                    for (const s of overflowingSections) {
                        // Hide from normal menu
                        s.classList.add("d-none");
                        // Show inside "more" menu
                        // Guard the lookup: an enterprise/website sub-menu
                        // patch may render a direct child carrying no
                        // ``data-section`` on itself or any descendant, and
                        // ``find`` may miss after a menus swap — never deref a
                        // null query result nor push ``undefined`` into the
                        // "More" menu.
                        const sectionNode = s.dataset.section
                            ? s
                            : s.querySelector("[data-section]");
                        const sectionId = sectionNode?.getAttribute("data-section");
                        if (!sectionId) {
                            continue;
                        }
                        const currentAppSection = this.currentAppSections.find(
                            (appSection) => appSection.id.toString() === sectionId,
                        );
                        if (currentAppSection) {
                            this.currentAppSectionsExtra.push(currentAppSection);
                        }
                    }
                    break;
                }
                width += sectionWidths[index];
            }
        }

        // ------- Final rendering -------
        const firstCurrentAppSectionExtra = [...this.currentAppSectionsExtra].shift();
        const currentAppId = firstCurrentAppSectionExtra?.appID;
        if (
            initialAppSectionsExtra.length === this.currentAppSectionsExtra.length &&
            initialAppId === currentAppId
        ) {
            // Do not render if more menu items stayed the same.
            return;
        }
        return this.render();
    }

    /** @param {Object} menu - the selected menu descriptor */
    onNavBarDropdownItemSelection(menu) {
        if (menu) {
            this.menuService.selectMenu(menu);
        }
    }

    /**
     * @param {Object} payload - menu item with actionPath or actionID
     * @returns {string} the URL path for the menu item
     */
    getMenuItemHref(payload) {
        return `/odoo/${payload.actionPath || `action-${payload.actionID}`}`;
    }

    _closeAppMenuSidebar() {
        this.state.isAllAppsMenuOpened = false;
        this.state.isAppMenuSidebarOpened = false;
    }
    _openAppMenuSidebar() {
        this.state.isAppMenuSidebarOpened = !this.state.isAppMenuSidebarOpened;
    }
    onAllAppsBtnClick() {
        this.state.isAllAppsMenuOpened = !this.state.isAllAppsMenuOpened;
    }
    async _onMenuClicked(menu) {
        // Close the sidebar whether or not the navigation completes: if a newer
        // navigation supersedes this one, selectMenu rejects with a
        // SupersededError (swallowed by the error service) — the `finally` still
        // closes the sidebar (was: sidebar stayed open on a never-settling await).
        try {
            await this.menuService.selectMenu(menu);
        } finally {
            this._closeAppMenuSidebar();
        }
    }
    _onSwipeStart(ev) {
        this.swipeStartX = ev.changedTouches[0].clientX;
    }
    _onSwipeEnd(ev) {
        if (!this.swipeStartX) {
            return;
        }
        const deltaX = this.swipeStartX - ev.changedTouches[0].clientX;
        // Disarm on every touchend, not just an activating one: a below-
        // threshold gesture used to leave the start point armed, so a later
        // touchend with no matching touchstart measured against a stale origin.
        this.swipeStartX = null;
        if (deltaX < SWIPE_ACTIVATION_THRESHOLD) {
            return;
        }
        this._closeAppMenuSidebar();
    }
}
