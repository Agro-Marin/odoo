// @ts-check
/** @odoo-module native */

import {
    Component,
    onMounted,
    onPatched,
    onWillRender,
    onWillUpdateProps,
    reactive,
    useRef,
    useState,
} from "@odoo/owl";
import { hasTouch, isIosApp } from "@web/core/browser/feature_detection";
import { useHotkey } from "@web/core/hotkeys/hotkey_hook";
import { _t } from "@web/core/translation";
import { useSortable } from "@web/core/utils/dnd";
import { useService } from "@web/core/utils/hooks";
import { fuzzyLookup } from "@web/core/utils/search";
import { menuUsage } from "@web/webclient/menus/menu_usage";
import {
    appSearchKey,
    flattenMenuTree,
    menuSearchKey,
    parseHomeMenuConfig,
} from "@web/webclient/menus/menu_utils";

import { appBadge, loadHomeMenuBadges } from "./badges.js";
import { ExpirationPanel } from "./expiration_panel.js";
import { gridRows, nextFocusedIndex } from "./grid_navigation.js";
import {
    HomeMenuLayout,
    orderAfterDrag,
    pinnedApps,
    shownApps,
} from "./home_menu_layout.js";
import { useHomeMenuSearch } from "./home_menu_search.js";
import { SysAdminPanel } from "./sysadmin_panel.js";

const EMPTY_MENU_TREE = { childrenTree: [] };

/** @param {{ xmlid?: string }[]} apps */
function homeMenuAppsKey(apps) {
    return apps.map((app) => app.xmlid ?? "").join("\u0000");
}

const APPS_PER_ROW = 6;
const SECTIONED_FROM = APPS_PER_ROW * 2;
const RECENT_APPS = 6;
const ATTENTION_APPS = 6;
const DIRECT_JUMP_HOTKEYS = 9;
const MENU_MATCHES = 8;

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
     *  focusedIndex: number | null;
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
    /**
     * The derived lists of the render being built. Every one of them walks
     * every app or every menu in the database, and they read each other:
     * the grid asks for its sections, the sections for the unpinned apps, the
     * unpinned for the pinned. Uncached, one keystroke rebuilt the fuzzy match
     * four times over.
     *
     * Cleared at the start of each render, so a handler reading one between
     * renders sees the render it is looking at. Nothing here may be read by a
     * handler that has just changed the state it derives from -- that state
     * change schedules the render this cache is keyed to.
     *
     * @type {Map<string, any>}
     */
    derived = new Map();

    setup() {
        this.menus = useService("menu");
        this.homeMenuService = useService("home_menu");
        this.subscription = useService("enterprise_subscription");
        this.state = useState({
            focusedIndex: null,
            isIosApp: isIosApp(),
            editing: false,
            badges: {},
        });
        this.search = useHomeMenuSearch({
            // A selection is an index into a grid the query is about to
            // refilter, so it stops meaning anything the moment the query moves.
            onQueryChanged: () => (this.state.focusedIndex = null),
        });
        this.layout = new HomeMenuLayout({
            config: useState(this.props.config ?? reactive(parseHomeMenuConfig(null))),
            defaultConfig: this.props.defaultConfig ?? parseHomeMenuConfig(null),
            orm: useService("orm"),
        });
        this.rootRef = useRef("root");

        onWillRender(() => this.derived.clear());

        this._registerHotkeys();

        useSortable({
            enable: () => this._enableAppsSorting(),
            // Params
            ref: this.rootRef,
            elements: ".o_draggable",
            ignore: ".o_app_edit_actions",
            cursor: "move",
            // Hooks
            onWillStartDrag: (params) => this._sortStart(params),
            onDrop: (params) => this._sortAppDrop(params),
        });

        this.appsKey = homeMenuAppsKey(this.props.apps);

        onWillUpdateProps((nextProps) => {
            // Keyed on which apps there are, not on the array's identity:
            // `MENUS_APP_CHANGED` fires for a plain navigation too, and mints
            // a fresh array and a fresh layout every time it does.
            const appsKey = homeMenuAppsKey(nextProps.apps);
            const appsChanged = appsKey !== this.appsKey;
            const configChanged =
                Boolean(nextProps.config) && nextProps.config !== this.props.config;
            if (appsChanged) {
                this.appsKey = appsKey;
                // A menu reload can install or remove an app, and its counts
                // are not the ones fetched at mount.
                this._loadBadges(nextProps.apps);
            }
            if (configChanged) {
                this.layout.setConfig(reactive(nextProps.config, () => this.render()));
            }
            if (nextProps.defaultConfig) {
                this.layout.defaultConfig = nextProps.defaultConfig;
            }
            // The keyboard selection is an index into a grid that just changed
            // shape, so it no longer points at what the user was looking at.
            // A re-render that leaves the grid alone keeps it.
            if (appsChanged || configChanged) {
                this.state.focusedIndex = null;
            }
        });

        onMounted(() => {
            if (!hasTouch()) {
                this.search.focus();
            }
            this._loadBadges();
        });

        onPatched(() => {
            // Only when an arrow key just moved the selection. Scrolling on
            // every patch instead would drag the grid back to a centred tile
            // under a user who had scrolled away from it, and cost a forced
            // layout for each unrelated render.
            if (!this.focusSelectedTile || this.env.isSmall) {
                return;
            }
            const selectedItem = /** @type {HTMLElement | null} */ (
                this.rootRef.el?.querySelector(".o_menuitem.o_focused")
            );
            if (!selectedItem) {
                return;
            }
            this.focusSelectedTile = false;
            // The arrow keys move the real focus: from the search box onto the
            // tiles, then between them, and the grid follows.
            selectedItem.focus({ preventScroll: true });
            selectedItem.scrollIntoView({ block: "center" });
        });
    }

    //--------------------------------------------------------------------------
    // Getters
    //--------------------------------------------------------------------------

    /** @returns {HomeMenuApp[]} */
    get displayedApps() {
        return this.props.apps;
    }

    /**
     * The tiles on screen, in the order they are on screen: pinned first in
     * their pinned order, then each section in turn. The keyboard indexes
     * into this, so it has to be the displayed order and not the stored one.
     *
     * @returns {HomeMenuApp[]}
     */
    get visibleApps() {
        if (!this.derived.has("visibleApps")) {
            this.derived.set("visibleApps", this._visibleApps());
        }
        return this.derived.get("visibleApps");
    }

    /** @returns {HomeMenuApp[]} */
    _visibleApps() {
        return [
            ...this.pinnedApps,
            ...this.appSections.flatMap((section) => section.apps),
        ];
    }

    /**
     * The unpinned tiles as the grid lays them out: one unlabelled section
     * while the grid is small enough to read whole, and while a query or the
     * edit mode is on -- a query has its own ordering, and a drag has to mean
     * one flat order or it means nothing.
     *
     * A section's place is where its first app sits in the stored order, so
     * dragging an app to the front brings its section with it.
     *
     * Each section carries where it starts in the flat keyboard order: a
     * running total cannot be kept in the template, where a `t-set` inside a
     * `t-foreach` is scoped to its own iteration and resets on the next.
     *
     * @returns {{ category: string, apps: HomeMenuApp[], offset: number }[]}
     */
    get appSections() {
        if (!this.derived.has("appSections")) {
            this.derived.set("appSections", this._appSections());
        }
        return this.derived.get("appSections");
    }

    /** @returns {{ category: string, apps: HomeMenuApp[], offset: number }[]} */
    _appSections() {
        const apps = this.unpinnedApps;
        const flat = [{ category: "", apps, offset: this.pinnedApps.length }];
        if (this.search.query || this.state.editing || apps.length <= SECTIONED_FROM) {
            return flat;
        }
        /** @type {Map<string, HomeMenuApp[]>} */
        const byCategory = new Map();
        for (const app of apps) {
            const category = app.category || _t("Other");
            const section = byCategory.get(category);
            if (section) {
                section.push(app);
            } else {
                byCategory.set(category, [app]);
            }
        }
        if (byCategory.size < 2) {
            return flat;
        }
        let offset = this.pinnedApps.length;
        return [...byCategory].map(([category, sectionApps]) => {
            const section = { category, apps: sectionApps, offset };
            offset += sectionApps.length;
            return section;
        });
    }

    /**
     * The apps the layout shows, before any query.
     *
     * @returns {HomeMenuApp[]}
     */
    get shownApps() {
        if (!this.derived.has("shownApps")) {
            this.derived.set("shownApps", this._shownApps());
        }
        return this.derived.get("shownApps");
    }

    /** @returns {HomeMenuApp[]} */
    _shownApps() {
        // While editing, the hidden ones are on screen too, dimmed, so they
        // can be brought back.
        return this.state.editing
            ? this.displayedApps
            : shownApps(this.layout.config, this.displayedApps);
    }

    /** @returns {HomeMenuApp[]} */
    get pinnedApps() {
        if (!this.derived.has("pinnedApps")) {
            this.derived.set("pinnedApps", this._pinnedApps());
        }
        return this.derived.get("pinnedApps");
    }

    /** @returns {HomeMenuApp[]} */
    _pinnedApps() {
        return this.search.query ? [] : pinnedApps(this.layout.config, this.shownApps);
    }

    /**
     * Under a query, every app the user has -- the hidden ones included, which
     * is what `HomeMenuConfig.hidden` has always promised and what the palette
     * has always done. Hiding an app declutters the grid; it is not a
     * permission, and an app the user asked for by name is not decluttered.
     * A hidden result keeps its dimming, so it still says what it is.
     *
     * @returns {HomeMenuApp[]}
     */
    get unpinnedApps() {
        if (!this.derived.has("unpinnedApps")) {
            this.derived.set("unpinnedApps", this._unpinnedApps());
        }
        return this.derived.get("unpinnedApps");
    }

    /** @returns {HomeMenuApp[]} */
    _unpinnedApps() {
        if (this.search.query) {
            return fuzzyLookup(this.search.query, this.displayedApps, appSearchKey, {
                preNormalized: true,
            });
        }
        return this.shownApps.filter((app) => !this.layout.isPinned(app));
    }

    /**
     * Reads `visibleApps` and not the cheaper `shownApps`, which holds the
     * same apps in a different order: `menuUsage.rank` sorts by frecency, and
     * `Array.sort` is stable, so two entries on the same count and the same
     * millisecond keep the order they arrived in. Rare, but it is a difference
     * in what the user sees, and the grid order is the one to show it in.
     *
     * @returns {HomeMenuApp[]}
     */
    get recentApps() {
        if (!this.derived.has("recentApps")) {
            this.derived.set("recentApps", this._recentApps());
        }
        return this.derived.get("recentApps");
    }

    /** @returns {HomeMenuApp[]} */
    _recentApps() {
        return this.search.query ? [] : menuUsage.rank(this.visibleApps, RECENT_APPS);
    }

    /** @returns {HomeMenuApp[]} */
    get attentionApps() {
        if (!this.derived.has("attentionApps")) {
            this.derived.set("attentionApps", this._attentionApps());
        }
        return this.derived.get("attentionApps");
    }

    /**
     * The apps with something waiting, most first.
     *
     * Recents answer "what do you use", which is not the same question and on a
     * grid this size is often not the same apps: a launcher of eighty tiles can
     * put the one with forty late transfers below the fold while showing six a
     * user opened yesterday out of habit. The counts were already on the tiles;
     * nothing ordered by them.
     *
     * A section rather than a re-sort of the grid, for the reason Pinned and
     * Recent are: a grid whose order moves with the data is a grid nobody can
     * learn the shape of.
     *
     * @returns {HomeMenuApp[]}
     */
    _attentionApps() {
        if (this.search.query || this.state.editing) {
            return [];
        }
        return this.visibleApps
            .filter((app) => this.badgeFor(app).count > 0)
            .sort((a, b) => this.badgeFor(b).count - this.badgeFor(a).count)
            .slice(0, ATTENTION_APPS);
    }

    /**
     * The menu items matching the query, deepest name first the way the
     * palette ranks them, so "quotations" beats "Sales / Orders / Quotations".
     *
     * @returns {import("@web/webclient/menus/menu_utils").MenuEntry[]}
     */
    get menuMatches() {
        if (!this.derived.has("menuMatches")) {
            this.derived.set("menuMatches", this._menuMatches());
        }
        return this.derived.get("menuMatches");
    }

    /** @returns {import("@web/webclient/menus/menu_utils").MenuEntry[]} */
    _menuMatches() {
        if (!this.search.query) {
            return [];
        }
        const { menuItems } = flattenMenuTree(
            this.menus.getMenuAsTree?.("root") ?? EMPTY_MENU_TREE,
        );
        return fuzzyLookup(this.search.query, menuItems, menuSearchKey, {
            preNormalized: true,
        }).slice(0, MENU_MATCHES);
    }

    /**
     * What a screen reader is told when the query moves: the grid collapsing
     * is the whole answer to a search, and it is silent to anyone not looking
     * at it.
     *
     * @returns {string}
     */
    get searchSummary() {
        if (!this.derived.has("searchSummary")) {
            this.derived.set("searchSummary", this._searchSummary());
        }
        return this.derived.get("searchSummary");
    }

    /** @returns {string} */
    _searchSummary() {
        if (!this.search.query) {
            return "";
        }
        const appCount = this.unpinnedApps.length;
        const menuCount = this.menuMatches.length;
        if (!appCount && !menuCount) {
            return _t("No apps or menus match");
        }
        return _t("%(apps)s apps and %(menus)s menus match", {
            apps: appCount,
            menus: menuCount,
        });
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
        return appBadge(this.state.badges, app);
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

    //--------------------------------------------------------------------------
    // Private
    //--------------------------------------------------------------------------

    /** @param {HomeMenuApp} menu */
    _openMenu(menu) {
        return this.menus.selectMenu(menu);
    }

    /**
     * @param {HomeMenuApp[]} [apps] the apps to count for, when the ones on
     *  `props` are not the ones about to be shown
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
        this.state.focusedIndex = null;
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
     * The item the keyboard selection points at: a tile, or past the tiles a
     * matching menu.
     *
     * @param {number} index
     */
    keyboardItem(index) {
        const apps = this.visibleApps;
        return index < apps.length
            ? apps[index]
            : this.menuMatches[index - apps.length];
    }

    _onEnter() {
        const focusedIndex = this.state.focusedIndex;
        if (focusedIndex !== null) {
            const appCount = this.visibleApps.length;
            const item = this.keyboardItem(focusedIndex);
            if (!item) {
                return;
            }
            return focusedIndex < appCount
                ? this._openMenu(/** @type {HomeMenuApp} */ (item))
                : this.menus.selectMenu(item);
        }
        if (!this.search.query) {
            return;
        }
        const [app] = this.unpinnedApps;
        if (app) {
            return this._openMenu(app);
        }
        const [menu] = this.menuMatches;
        if (menu) {
            return this.menus.selectMenu(menu);
        }
    }

    /** @param {import("@web/webclient/menus/menu_utils").MenuEntry} menu */
    _onMenuResultClick(menu) {
        return this.menus.selectMenu(menu);
    }

    /**
     * The tiles as rows: the pinned ones first, then the rest, each section
     * wrapping at the grid's width, so the arrows follow what is on screen.
     *
     * @returns {number[][]} visible indices, row by row
     */
    get keyboardRows() {
        return gridRows(
            [
                this.pinnedApps.length,
                ...this.appSections.map((section) => section.apps.length),
            ],
            APPS_PER_ROW,
            this.menuMatches.length,
        );
    }

    /** @param {string} cmd */
    _updateFocusedIndex(cmd) {
        const next = nextFocusedIndex(this.keyboardRows, this.state.focusedIndex, cmd);
        if (next === null) {
            return;
        }
        // The arrows move the real focus, not just the highlight.
        this.focusSelectedTile = true;
        this.state.focusedIndex = next;
    }

    // Rearranging is an edit, like pinning: outside the edit mode a slow
    // click stays a click.
    _enableAppsSorting() {
        return this.state.editing;
    }

    //--------------------------------------------------------------------------
    // Handlers
    //--------------------------------------------------------------------------

    /** @param {import("@web/core/utils/dnd/sortable").DropParams} params */
    _sortAppDrop({ element, previous }) {
        const movedId = /** @type {HTMLElement} */ (element.children[0]).dataset
            .menuXmlid;
        if (movedId === undefined) {
            // An app the DOM cannot name has no place in a stored order.
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
        this.state.focusedIndex = index;
    }

    _registerHotkeys() {
        const isAvailable = () => !this.env.isSmall;
        /** @type {[string, () => void][]} */
        const hotkeys = [
            ["ArrowDown", () => this._updateFocusedIndex("nextLine")],
            ["ArrowRight", () => this._updateFocusedIndex("nextColumn")],
            ["ArrowUp", () => this._updateFocusedIndex("previousLine")],
            ["ArrowLeft", () => this._updateFocusedIndex("previousColumn")],
            ["Escape", () => this._onEscape()],
        ];
        for (const [hotkey, callback] of hotkeys) {
            useHotkey(hotkey, callback, { allowRepeat: true, isAvailable });
        }
        // A tile with the real focus is a link: Enter is its own click.
        useHotkey("Enter", () => this._onEnter(), {
            allowRepeat: true,
            isAvailable: (target) => isAvailable() && target === this.search.inputEl,
        });
    }
}
