// @ts-check
/** @odoo-module native */

/** @module @web/webclient/navbar/navbar */

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
import { reportUncaught } from "@web/core/errors/error_utils";
import { AppEvent } from "@web/core/events";
import { registry } from "@web/core/registry";
import { Transition } from "@web/core/transition";
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

const MORE_MENU_WIDTH = 46;

export class NavBar extends Component {
    static template = "web.NavBar";
    static components = {
        Dropdown,
        DropdownItem,
        DropdownGroup,
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
     * @param {Object} item
     */
    handleItemError(error, item) {
        this.failedSystrayKeys.add(item.key);
        reportUncaught(error);
    }

    /** @returns {Object | undefined} */
    get currentApp() {
        return this.menuService.getCurrentApp();
    }

    /** @returns {Object[]} */
    get currentAppSections() {
        return (
            (this.currentApp &&
                this.menuService.getMenuAsTree(this.currentApp.id).childrenTree) ||
            []
        );
    }

    /**
     * Never called. It exists so `patch()` can install a getter-only override
     * without the property losing its setter: `website` overrides this getter
     * (`website/components/navbar/navbar.js`, `.../burger_menu/burger_menu.js`)
     * on top of the Enterprise NavBar extension, and the two conflict on a
     * property that is get-only.
     */
    set currentAppSections(_) {}

    get isScopedApp() {
        return this.pwa.isScopedApp;
    }

    /** @returns {Object[]} */
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

    /** Never called; see {@link NavBar#currentAppSections}'s setter. */
    set systrayItems(_) {}

    adapt() {
        if (!this.root.el) {
            return;
        }

        const sectionsMenu = this.appSubMenus.el;
        if (!sectionsMenu) {
            return;
        }

        const initialAppSectionsExtra = this.currentAppSectionsExtra;

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

        // Entry by entry, by identity. `getMenuAsTree` hands back the same
        // objects until the menu service rebuilds its tree, so identity is
        // exactly "the payload these sections came from is unchanged" — which
        // also covers the app having changed. Comparing the LENGTH and the
        // first entry's appID instead let a menu reload that swapped sections
        // within one app through the guard: the render that carried the new
        // sections had already happened with the previous overflow list, so
        // the "more" dropdown went on offering menus that no longer existed.
        if (
            initialAppSectionsExtra.length === this.currentAppSectionsExtra.length &&
            initialAppSectionsExtra.every(
                (section, index) => section === this.currentAppSectionsExtra[index],
            )
        ) {
            return;
        }
        return this.render();
    }

    /** @param {Object} menu */
    onNavBarDropdownItemSelection(menu) {
        if (menu) {
            this.menuService.selectMenu(menu);
        }
    }

    /**
     * @param {Object} payload
     * @returns {string}
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
