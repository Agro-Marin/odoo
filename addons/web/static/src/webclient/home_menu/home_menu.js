// @ts-check
/** @odoo-module native */

import {
    Component,
    onMounted,
    onWillRender,
    onWillUnmount,
    onWillUpdateProps,
    reactive,
    useRef,
    useState,
} from "@odoo/owl";
import { browser } from "@web/core/browser/browser";
import { hasTouch, isIosApp } from "@web/core/browser/feature_detection";
import { _t } from "@web/core/translation";
import { useSortable } from "@web/core/utils/dnd";
import { useService } from "@web/core/utils/hooks";
import { parseHomeMenuConfig } from "@web/webclient/menus/menu_utils";

import { loadHomeMenuBadges } from "./badges.js";
import { ExpirationPanel } from "./expiration_panel.js";
import { gridRows } from "./grid_navigation.js";
import { HomeMenuGrid } from "./home_menu_grid.js";
import { useHomeMenuKeyboard } from "./home_menu_keyboard.js";
import { HomeMenuLayout, orderAfterDrag } from "./home_menu_layout.js";
import { useHomeMenuSearch } from "./home_menu_search.js";
import { SysAdminPanel } from "./sysadmin_panel.js";

/** @param {{ xmlid?: string }[]} apps */
function homeMenuAppsKey(apps) {
    return apps.map((app) => app.xmlid ?? "").join("\u0000");
}

const APPS_PER_ROW = 6;
// The launcher is the client's landing page, so it mounts on every cold load
// and is replaced a few round trips later by whatever the url actually asked
// for. Counting for a launcher nobody sees is a wasted request on every deep
// link, and it put `get_badges` in the middle of the boot sequence of every
// test that records network calls. Long enough to outlive that mount, short
// enough that a user who did land here sees the counts arrive with the page.
const BADGE_DELAY = 200;
const DIRECT_JUMP_HOTKEYS = 9;

/**
 * @typedef {import("@web/webclient/menus/menu_utils").AppEntry} HomeMenuApp
 */

export class HomeMenu extends Component {
    static template = "web.HomeMenu";
    static appTemplate = "web.HomeMenu.App";
    static components = { ExpirationPanel, SysAdminPanel };
    static props = {
        apps: {
            type: Array,
            element: {
                type: Object,
                shape: {
                    actionID: Number,
                    href: String,
                    appID: Number,
                    id: Number,
                    label: String,
                    parents: String,
                    module: { type: String, optional: true },
                    category: { type: String, optional: true },
                    models: { type: Array, element: String, optional: true },
                    keywords: { type: Array, element: String, optional: true },
                    searchTerms: { type: Array, element: String, optional: true },
                    webIcon: {
                        type: [
                            Boolean,
                            String,
                            {
                                type: Object,
                                optional: 1,
                                shape: {
                                    iconClass: String,
                                    color: String,
                                    backgroundColor: String,
                                },
                            },
                        ],
                        optional: true,
                    },
                    webIconData: { type: String, optional: 1 },
                    xmlid: { type: String, optional: true },
                },
            },
        },
        reorderApps: { type: Function },
        config: {
            type: Object,
            optional: true,
            shape: { order: Array, pinned: Array, hidden: Array },
        },
        resetApps: { type: Function, optional: true },
        defaultConfig: {
            type: Object,
            optional: true,
            shape: { order: Array, pinned: Array, hidden: Array },
        },
    };

    /**
     * @type {{
     *  isIosApp: boolean;
     *  editing: boolean;
     *  badges: Record<string, number>;
     * }}
     */
    state;
    /**
     * Which apps are pinned, hidden and in what order, and the writing of it
     * down. The grid reads it; it owns it.
     *
     * @type {HomeMenuLayout}
     */
    layout;
    /** @type {boolean} */
    focusSelectedTile = false;
    /** @type {ReturnType<typeof useHomeMenuSearch>} */
    search;

    /** @type {import("services").ServiceFactories["menu"]} */
    menus;
    /** @type {import("services").ServiceFactories["home_menu"]} */
    homeMenuService;
    /** @type {import("services").ServiceFactories["enterprise_subscription"]} */
    subscription;
    /** @type {import("@odoo/owl").Ref<HTMLElement>} */
    rootRef;
    setup() {
        this.menus = useService("menu");
        this.homeMenuService = useService("home_menu");
        this.subscription = useService("enterprise_subscription");
        this.state = useState({
            isIosApp: isIosApp(),
            editing: false,
            badges: {},
        });
        this.search = useHomeMenuSearch({
            onQueryChanged: () => this.keyboard.clear(),
        });
        this.layout = new HomeMenuLayout({
            config: useState(this.props.config ?? reactive(parseHomeMenuConfig(null))),
            defaultConfig: this.props.defaultConfig ?? parseHomeMenuConfig(null),
            orm: useService("orm"),
        });
        this.rootRef = useRef("root");

        this.grid = new HomeMenuGrid({
            apps: () => this.props.apps,
            query: () => this.search.query,
            editing: () => this.state.editing,
            badges: () => this.state.badges,
            layout: this.layout,
            menus: this.menus,
        });
        onWillRender(() => this.grid.clear());

        this.keyboard = useHomeMenuKeyboard({
            rows: () => this.keyboardRows,
            activate: (index) => this._activate(index),
            fallback: () => this._openFirstMatch(),
            escape: () => this._onEscape(),
            isAvailable: () => !this.env.isSmall,
            enterTarget: () => this.search.inputEl,
        });

        useSortable({
            enable: () => this._enableAppsSorting(),
            ref: this.rootRef,
            elements: ".o_draggable",
            ignore: ".o_app_edit_actions",
            cursor: "move",
            onWillStartDrag: (params) => this._sortStart(params),
            onDrop: (params) => this._sortAppDrop(params),
        });

        this.appsKey = homeMenuAppsKey(this.props.apps);

        onWillUpdateProps((nextProps) => {
            const appsKey = homeMenuAppsKey(nextProps.apps);
            const appsChanged = appsKey !== this.appsKey;
            const configChanged =
                Boolean(nextProps.config) && nextProps.config !== this.props.config;
            if (appsChanged) {
                this.appsKey = appsKey;
                this._loadBadges(nextProps.apps);
            }
            if (configChanged) {
                this.layout.setConfig(reactive(nextProps.config, () => this.render()));
            }
            if (nextProps.defaultConfig) {
                this.layout.defaultConfig = nextProps.defaultConfig;
            }
            if (appsChanged || configChanged) {
                this.keyboard.clear();
            }
        });

        onMounted(() => {
            if (!hasTouch()) {
                this.search.focus();
            }
            this.badgeTimer = browser.setTimeout(() => this._loadBadges(), BADGE_DELAY);
        });

        onWillUnmount(() => browser.clearTimeout(this.badgeTimer));
    }

    /** @returns {HomeMenuApp[]} */
    get displayedApps() {
        return this.props.apps;
    }

    /** @returns {boolean} */
    get canEditLayout() {
        return true;
    }

    /** @returns {boolean} */
    get hasCustomLayout() {
        return this.layout.isCustomised;
    }

    /** @returns {boolean} */
    get canSetCompanyDefault() {
        return this.layout.canSetCompanyDefault;
    }

    /** @param {HomeMenuApp} app */
    badgeFor(app) {
        return this.grid.badgeOf(app);
    }

    /** @param {HomeMenuApp} app */
    pinTitle(app) {
        return this.layout.isPinned(app) ? _t("Unpin") : _t("Pin");
    }

    /** @param {HomeMenuApp} app */
    hideTitle(app) {
        return this.layout.isHidden(app) ? _t("Show") : _t("Hide");
    }

    /** @returns {number} */
    get directJumpHotkeys() {
        return DIRECT_JUMP_HOTKEYS;
    }

    /** @param {HomeMenuApp} menu */
    _openMenu(menu) {
        return this.menus.selectMenu(menu);
    }

    /**
     * @param {HomeMenuApp[]} [apps] the apps to count for, when the ones on
     */
    async _loadBadges(apps) {
        this.state.badges = await loadHomeMenuBadges(
            /** @type {import("@web/env").OdooEnv} */ (
                /** @type {unknown} */ (this.env)
            ),
            apps ?? this.displayedApps,
            { refresh: true },
        );
    }

    /** @param {HomeMenuApp} app */
    _togglePinned(app) {
        return this.layout.togglePinned(app);
    }

    /** @param {HomeMenuApp} app */
    _toggleHidden(app) {
        return this.layout.toggleHidden(app);
    }

    _resetLayout() {
        const { order, saved } = this.layout.reset();
        this.props.resetApps?.(order);
        return saved;
    }

    async _setCompanyDefault() {
        await this.layout.setCompanyDefault();
        this.render();
    }

    _toggleEditing() {
        this.state.editing = !this.state.editing;
        this.keyboard.clear();
    }

    _onEscape() {
        if (this.search.query) {
            this.search.clear();
        } else if (this.state.editing) {
            this._toggleEditing();
        } else {
            this.homeMenuService.toggle(false);
        }
    }

    /**
     * @param {number} index
     */
    keyboardItem(index) {
        const apps = this.grid.visibleApps;
        return index < apps.length
            ? apps[index]
            : this.grid.menuMatches[index - apps.length];
    }

    /** @param {number} index into the flat keyboard order */
    _activate(index) {
        const item = this.keyboardItem(index);
        if (!item) {
            return;
        }
        return index < this.grid.visibleApps.length
            ? this._openMenu(/** @type {HomeMenuApp} */ (item))
            : this.menus.selectMenu(item);
    }

    _openFirstMatch() {
        if (!this.search.query) {
            return;
        }
        const [app] = this.grid.unpinnedApps;
        if (app) {
            return this._openMenu(app);
        }
        const [menu] = this.grid.menuMatches;
        if (menu) {
            return this.menus.selectMenu(menu);
        }
    }

    /** @param {import("@web/webclient/menus/menu_utils").MenuEntry} menu */
    _onMenuResultClick(menu) {
        return this.menus.selectMenu(menu);
    }

    /**
     * @returns {number[][]} visible indices, row by row
     */
    get keyboardRows() {
        return gridRows(
            this.grid.keyboardRows,
            APPS_PER_ROW,
            this.grid.menuMatches.length,
        );
    }

    _enableAppsSorting() {
        return this.state.editing;
    }

    /** @param {import("@web/core/utils/dnd/sortable").DropParams} params */
    _sortAppDrop({ element, previous }) {
        const movedId = /** @type {HTMLElement} */ (element.children[0]).dataset
            .menuXmlid;
        if (movedId === undefined) {
            return;
        }
        const order = orderAfterDrag(
            this.displayedApps.flatMap((app) =>
                app.xmlid === undefined ? [] : [app.xmlid],
            ),
            movedId,
            /** @type {HTMLElement} */ (previous?.children[0])?.dataset.menuXmlid,
        );
        if (!order) {
            return;
        }
        this.props.reorderApps(order);
        this.layout.setOrder(order);
    }

    /** @param {import("@web/core/utils/dnd/sortable").SortableHandlerParams} params */
    _sortStart({ element, addClass }) {
        addClass(/** @type {HTMLElement} */ (element.children[0]), "o_dragged_app");
    }

    /** @param {HomeMenuApp} app */
    _onAppClick(app) {
        this._openMenu(app);
    }

    /** @param {number} index into the flat keyboard order */
    _onItemFocus(index) {
        this.keyboard.focus(index);
    }
}
