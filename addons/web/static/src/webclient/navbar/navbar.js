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

import { SWIPE_LEFT, SwipeTracker } from "../swipe.js";
const systrayRegistry = registry.category("systray");

systrayRegistry.addValidation({
    Component: { validate: (c) => c?.prototype instanceof Component },
    props: { type: Object, optional: true },
    isDisplayed: { type: Function, optional: true },
    "*": true,
});

const getBoundingClientRect = Element.prototype.getBoundingClientRect;

/**
 * Width reserved for the overflow ("More") toggle when deciding how many
 * sections fit. Budgeted up front because the toggle only exists once at least
 * one section has overflowed — measuring it is impossible before the decision
 * that creates it.
 */
const MORE_MENU_WIDTH = 46;

/** Dropdown subclass for navbar sub-menus (enables enterprise/website patching). */
export class MenuDropdown extends Dropdown {}

/**
 * Main navigation bar at the top of the webclient.
 *
 * Renders the app switcher, current app's sub-menus (with overflow "More" menu),
 * systray items, and mobile sidebar. Re-measures on a debounced window resize.
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

        onWillDestroy(() => {
            systrayRegistry.removeEventListener("UPDATE", renderAndAdapt);
            this.env.bus.removeEventListener(
                AppEvent.MENUS_APP_CHANGED,
                renderAndAdapt,
            );
        });

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
        this.swipe = new SwipeTracker(SWIPE_LEFT);
    }

    /**
     * @param {Error} error
     * @param {Object} item - the systray item that errored
     */
    handleItemError(error, item) {
        this.failedSystrayKeys.add(item.key);
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

    /**
     * Deliberate no-op, and NOT dead code — see the note on {@link systrayItems}.
     */
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

    /**
     * Deliberate no-op paired with the getter above: `website` patches
     * `systrayItems` (and {@link currentAppSections}) as a getter with no
     * setter, and `patch()` fills the missing half from the ancestor descriptor
     * (`core/utils/patch.js`, the `Boolean(get) !== Boolean(set)` branch). Drop
     * this and the patched property becomes getter-only, so any assignment
     * throws inside another addon's patch.
     */
    set systrayItems(_) {}

    /**
     * Compute the available width for app sections; if they overflow, move
     * the minimum needed sections into a "more" menu.
     *
     * NB: requires an upfront render to measure section widths, and may
     * trigger another render afterward depending on the outcome.
     */
    adapt() {
        if (!this.root.el) {
            /** @todo do we still need this check? */
            return;
        }

        const sectionsMenu = this.appSubMenus.el;
        if (!sectionsMenu) {
            return;
        }

        const initialAppSectionsExtra = this.currentAppSectionsExtra;
        const initialAppId = initialAppSectionsExtra[0]?.appID;

        const sections = [
            ...sectionsMenu.querySelectorAll(":scope > *:not(.o_menu_sections_more)"),
        ];
        for (const section of sections) {
            section.classList.remove("d-none");
        }
        this.currentAppSectionsExtra = [];

        const sectionsAvailableWidth = getBoundingClientRect.call(sectionsMenu).width;
        const sectionWidths = sections.map((s) => getBoundingClientRect.call(s).width);
        const sectionsTotalWidth = sectionWidths.reduce((sum, w) => sum + w, 0);
        if (sectionsAvailableWidth < sectionsTotalWidth) {
            let width = MORE_MENU_WIDTH;
            for (let index = 0; index < sections.length; index++) {
                if (sectionsAvailableWidth < width + sectionWidths[index]) {
                    const overflowingSections = sections.slice(index);
                    for (const s of overflowingSections) {
                        s.classList.add("d-none");
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

        const currentAppId = this.currentAppSectionsExtra[0]?.appID;
        if (
            initialAppSectionsExtra.length === this.currentAppSectionsExtra.length &&
            initialAppId === currentAppId
        ) {
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
        try {
            await this.menuService.selectMenu(menu);
        } finally {
            this._closeAppMenuSidebar();
        }
    }
    _onSwipeStart(ev) {
        this.swipe.start(ev);
    }
    _onSwipeEnd(ev) {
        if (this.swipe.end(ev)) {
            this._closeAppMenuSidebar();
        }
    }
}
