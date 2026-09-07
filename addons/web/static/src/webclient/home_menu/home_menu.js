// @ts-check
/** @odoo-module native */

import {
    Component,
    onMounted,
    onPatched,
    onWillUpdateProps,
    reactive,
    useExternalListener,
    useRef,
    useState,
} from "@odoo/owl";
import { browser } from "@web/core/browser/browser";
import { hasTouch, isIosApp, isMacOS } from "@web/core/browser/feature_detection";
import { useHotkey } from "@web/core/hotkeys/hotkey_hook";
import { registry } from "@web/core/registry";
import { _t } from "@web/core/translation";
import { useSortable } from "@web/core/utils/dnd";
import { useService } from "@web/core/utils/hooks";
import { fuzzyLookup } from "@web/core/utils/search";
import { menuUsage } from "@web/webclient/menus/menu_usage";
import {
    flattenMenuTree,
    menuSearchKey,
    parseHomeMenuConfig,
} from "@web/webclient/menus/menu_utils";

import { appBadge, loadHomeMenuBadges } from "./badges.js";
import { ExpirationPanel } from "./expiration_panel.js";
import { gridRows, nextFocusedIndex } from "./grid_navigation.js";
import { HomeMenuLayout } from "./home_menu_layout.js";
import { SysAdminPanel } from "./sysadmin_panel.js";

// A stable object, so a menu service without `getMenuAsTree` still resolves
// against the flattened-tree cache instead of missing it on a fresh literal.
const EMPTY_MENU_TREE = { childrenTree: [] };

/** @param {{ xmlid?: string }[]} apps */
function homeMenuAppsKey(apps) {
    return apps.map((app) => app.xmlid ?? "").join("\u0000");
}

const APPS_PER_ROW = 6;
const RECENT_APPS = 6;
const DIRECT_JUMP_HOTKEYS = 9;
const MENU_MATCHES = 8;

class FooterComponent extends Component {
    static template = "web.HomeMenu.CommandPalette.Footer";
    static props = {
        //prop added by the command palette
        switchNamespace: { type: Function, optional: true },
    };

    setup() {
        this.controlKey = isMacOS() ? "COMMAND" : "CONTROL";
    }
}

/**
 * The launcher's name for what `computeAppsAndMenuItems` calls an app. It was
 * a second declaration of the same record, and the two had drifted: this one
 * made `xmlid` required, which every reader of it already disbelieved --
 * `isPinned`, `isHidden`, `badgeFor` and `_sortAppDrop` all test it against
 * `undefined` first.
 *
 * @typedef {import("@web/webclient/menus/menu_utils").AppEntry} HomeMenuApp
 */

/**
 * Home menu
 *
 * This component handles the display and navigation between the different
 * available applications and menus.
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
                    models: { type: Array, element: String, optional: true },
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
     *  query: string;
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
    compositionStart = false;
    /** @type {boolean} */
    focusSelectedTile = false;

    /** @type {import("services").ServiceFactories["command"]} */
    command;
    /** @type {import("services").ServiceFactories["menu"]} */
    menus;
    /** @type {import("services").ServiceFactories["home_menu"]} */
    homeMenuService;
    /** @type {import("services").ServiceFactories["enterprise_subscription"]} */
    subscription;
    /** @type {import("services").ServiceFactories["ui"]} */
    ui;
    /** @type {import("services").ServiceFactories["orm"]} */
    orm;
    /** @type {import("@odoo/owl").Ref<HTMLElement>} */
    inputRef;
    /** @type {import("@odoo/owl").Ref<HTMLElement>} */
    rootRef;

    setup() {
        this.command = useService("command");
        this.menus = useService("menu");
        this.homeMenuService = useService("home_menu");
        this.subscription = useService("enterprise_subscription");
        this.ui = useService("ui");
        this.orm = useService("orm");
        this.state = useState({
            focusedIndex: null,
            isIosApp: isIosApp(),
            editing: false,
            badges: {},
            query: "",
        });
        this.layout = new HomeMenuLayout({
            config: useState(this.props.config ?? reactive(parseHomeMenuConfig(null))),
            defaultConfig: this.props.defaultConfig ?? parseHomeMenuConfig(null),
            orm: this.orm,
        });
        this.inputRef = useRef("input");
        this.rootRef = useRef("root");

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

        onWillUpdateProps((nextProps) => {
            // State is reset on each remount
            this.state.focusedIndex = null;
            if (nextProps.config && nextProps.config !== this.props.config) {
                this.layout.setConfig(reactive(nextProps.config, () => this.render()));
            }
            if (nextProps.defaultConfig) {
                this.layout.defaultConfig = nextProps.defaultConfig;
            }
            // A menu reload can install or remove an app; its counts are not
            // the ones fetched at mount. Keyed on which apps there are, not on
            // the array's identity, because `MENUS_APP_CHANGED` also fires for
            // a plain navigation and mints a fresh array every time.
            const appsKey = homeMenuAppsKey(nextProps.apps);
            if (appsKey !== this.appsKey) {
                this.appsKey = appsKey;
                this._loadBadges(nextProps.apps);
            }
        });

        this.appsKey = homeMenuAppsKey(this.props.apps);

        onMounted(() => {
            if (!hasTouch()) {
                this._focusInput();
            }
            this._loadBadges();
        });

        onPatched(() => {
            if (this.state.focusedIndex !== null && !this.env.isSmall) {
                const selectedItem = /** @type {HTMLElement | null} */ (
                    this.rootRef.el?.querySelector(".o_menuitem.o_focused")
                );
                if (selectedItem) {
                    // The arrow keys move the real focus: from the search box
                    // onto the tiles, then between them.
                    if (this.focusSelectedTile) {
                        this.focusSelectedTile = false;
                        selectedItem.focus({ preventScroll: true });
                    }
                    selectedItem.scrollIntoView({ block: "center" });
                }
            }
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
     * The tiles on screen: pinned first in their pinned order, then the rest
     * in the stored order, hidden ones only while editing.
     *
     * @returns {HomeMenuApp[]}
     */
    get visibleApps() {
        return [...this.pinnedApps, ...this.unpinnedApps];
    }

    /**
     * The apps the layout shows, before any query.
     *
     * @returns {HomeMenuApp[]}
     */
    get shownApps() {
        return this.displayedApps.filter((app) => this._isShown(app));
    }

    /** @returns {HomeMenuApp[]} */
    get pinnedApps() {
        if (this.state.query) {
            return [];
        }
        const byXmlid = new Map(
            this.displayedApps
                .filter((app) => app.xmlid !== undefined && this._isShown(app))
                .map((app) => [app.xmlid, app]),
        );
        return this.layout.config.pinned.flatMap((xmlid) => {
            const app = byXmlid.get(xmlid);
            return app ? [app] : [];
        });
    }

    /** @returns {HomeMenuApp[]} */
    get unpinnedApps() {
        if (this.state.query) {
            return fuzzyLookup(this.state.query, this.shownApps, (app) => app.label);
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
        return this.state.query ? [] : menuUsage.rank(this.visibleApps, RECENT_APPS);
    }

    /**
     * The menu items matching the query, deepest name first the way the
     * palette ranks them, so "quotations" beats "Sales / Orders / Quotations".
     *
     * @returns {import("@web/webclient/menus/menu_utils").MenuEntry[]}
     */
    get menuMatches() {
        if (!this.state.query) {
            return [];
        }
        const { menuItems } = flattenMenuTree(
            this.menus.getMenuAsTree?.("root") ?? EMPTY_MENU_TREE,
        );
        return fuzzyLookup(this.state.query, menuItems, menuSearchKey, {
            preNormalized: true,
        }).slice(0, MENU_MATCHES);
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

    /** @returns {HTMLInputElement | null} */
    get inputEl() {
        return /** @type {HTMLInputElement | null} */ (this.inputRef.el);
    }

    /** @returns {number} */
    get maxIconNumber() {
        return APPS_PER_ROW;
    }

    //--------------------------------------------------------------------------
    // Private
    //--------------------------------------------------------------------------

    /** @param {HomeMenuApp} menu */
    _openMenu(menu) {
        return this.menus.selectMenu(menu);
    }

    /** @param {HomeMenuApp} app */
    _isShown(app) {
        return this.state.editing || !this.layout.isHidden(app);
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

    _clearQuery() {
        this.state.query = "";
        this.state.focusedIndex = null;
        if (this.inputEl) {
            this.inputEl.value = "";
        }
    }

    _onEscape() {
        if (this.state.query) {
            this._clearQuery();
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
        if (!this.state.query) {
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
    /** @returns {number[][]} visible indices, row by row */
    get keyboardRows() {
        return gridRows(
            [this.pinnedApps.length, this.unpinnedApps.length],
            this.maxIconNumber,
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

    _focusInput() {
        if (!this.env.isSmall && this.inputRef.el) {
            this.inputRef.el.focus({ preventScroll: true });
        }
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
        const elementId = /** @type {HTMLElement} */ (element.children[0]).dataset
            .menuXmlid;
        if (elementId === undefined) {
            // An app the DOM cannot name cannot be placed in a stored order,
            // and splicing at indexOf's -1 would move the last app instead.
            return;
        }
        /** @type {string[]} */
        const order = [];
        for (const app of this.displayedApps) {
            if (app.xmlid !== undefined) {
                order.push(app.xmlid);
            }
        }
        const elementIndex = order.indexOf(elementId);
        // first remove dragged element
        order.splice(elementIndex, 1);
        const previousId =
            previous &&
            /** @type {HTMLElement} */ (previous.children[0]).dataset.menuXmlid;
        if (previousId) {
            // insert dragged element after previous element
            order.splice(order.indexOf(previousId) + 1, 0, elementId);
        } else {
            // insert dragged element at beginning if no previous element
            order.splice(0, 0, elementId);
        }
        // apply new order
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
            isAvailable: (target) => isAvailable() && target === this.inputEl,
        });
        useExternalListener(window, "keydown", this._onKeydownFocusInput);
    }

    /** @param {KeyboardEvent} ev */
    _onKeydownFocusInput(ev) {
        const isPrintable =
            ev.key.length === 1 && !ev.ctrlKey && !ev.metaKey && !ev.altKey;
        if (
            isPrintable &&
            document.activeElement !== this.inputRef.el &&
            this.ui.activeElement === document &&
            !["TEXTAREA", "INPUT"].includes(document.activeElement?.tagName ?? "")
        ) {
            this._focusInput();
        }
    }

    _onInputSearch() {
        const typed = this.compositionStart ? "" : (this.inputEl?.value.trim() ?? "");
        this.compositionStart = false;
        // A leading namespace character the palette knows is the user's
        // choice of namespace and goes to the palette; anything else filters
        // the tiles here and lists the matching menus below them.
        const isNamespace =
            typed.length > 0 && registry.category("command_setup").contains(typed[0]);
        if (!isNamespace) {
            this.state.query = typed;
            this.state.focusedIndex = null;
            return;
        }
        this._clearQuery();
        this.command.openMainPalette(
            /** @type {any} */ ({ searchValue: typed, FooterComponent }),
            () => this._focusInput(),
        );
    }

    _onInputBlur() {
        if (hasTouch()) {
            return;
        }
        // if we blur search input to focus on body (eg. click on any
        // non-interactive element) restore focus to avoid IME input issue
        browser.setTimeout(() => {
            if (
                document.activeElement === document.body &&
                this.ui.activeElement === document
            ) {
                this._focusInput();
            }
        });
    }

    _onCompositionStart() {
        this.compositionStart = true;
    }
}
