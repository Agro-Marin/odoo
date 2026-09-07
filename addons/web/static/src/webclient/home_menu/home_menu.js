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
import { user } from "@web/core/user";
import { useSortable } from "@web/core/utils/dnd";
import { useService } from "@web/core/utils/hooks";
import { session } from "@web/session";
import { menuUsage } from "@web/webclient/menus/menu_usage";
import {
    parseHomeMenuConfig,
    serializeHomeMenuConfig,
} from "@web/webclient/menus/menu_utils";

import { loadHomeMenuBadges } from "./badges.js";
import { ExpirationPanel } from "./expiration_panel.js";
import { SysAdminPanel } from "./sysadmin_panel.js";

const APPS_PER_ROW = 6;
const RECENT_APPS = 6;
const DIRECT_JUMP_HOTKEYS = 9;

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
 * @typedef {{
 *  actionID: number;
 *  href: string;
 *  appID: number;
 *  id: number;
 *  label: string;
 *  parents: string;
 *  module?: string;
 *  models?: string[];
 *  webIcon?: boolean | string | { iconClass: string; color: string; backgroundColor: string };
 *  webIconData?: string;
 *  xmlid: string;
 * }} HomeMenuApp
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

    /** @type {{ focusedIndex: number | null; isIosApp: boolean; editing: boolean; badges: Record<string, number> }} */
    state;
    /** @type {import("@web/webclient/menus/menu_utils").HomeMenuConfig} */
    config;
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
        });
        this.config = useState(
            this.props.config ?? reactive(parseHomeMenuConfig(null)),
        );
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
                this.config = reactive(nextProps.config, () => this.render());
            }
        });

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

    /** @returns {HomeMenuApp[]} */
    get pinnedApps() {
        const byXmlid = new Map(
            this.displayedApps
                .filter((app) => app.xmlid !== undefined && this._isShown(app))
                .map((app) => [app.xmlid, app]),
        );
        return this.config.pinned.flatMap((xmlid) => {
            const app = byXmlid.get(xmlid);
            return app ? [app] : [];
        });
    }

    /** @returns {HomeMenuApp[]} */
    get unpinnedApps() {
        return this.displayedApps.filter(
            (app) => !this.isPinned(app) && this._isShown(app),
        );
    }

    /** @returns {HomeMenuApp[]} */
    get recentApps() {
        return menuUsage.rank(this.visibleApps, RECENT_APPS);
    }

    /** @returns {boolean} */
    get canEditLayout() {
        return true;
    }

    /** @returns {import("@web/webclient/menus/menu_utils").HomeMenuConfig} */
    get defaultConfig() {
        return this.props.defaultConfig ?? parseHomeMenuConfig(null);
    }

    /** @returns {boolean} */
    get hasCustomLayout() {
        return (
            serializeHomeMenuConfig(this.config) !==
            serializeHomeMenuConfig(this.defaultConfig)
        );
    }

    /** @returns {boolean} */
    get canSetCompanyDefault() {
        return user.isAdmin;
    }

    /**
     * @param {HomeMenuApp} app
     * @returns {number}
     */
    badgeFor(app) {
        return app.xmlid === undefined ? 0 : this.state.badges[app.xmlid] || 0;
    }

    /** @param {HomeMenuApp} app */
    isPinned(app) {
        return app.xmlid !== undefined && this.config.pinned.includes(app.xmlid);
    }

    /** @param {HomeMenuApp} app */
    isHidden(app) {
        return app.xmlid !== undefined && this.config.hidden.includes(app.xmlid);
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
        return this.state.editing || !this.isHidden(app);
    }

    async _loadBadges() {
        this.state.badges = await loadHomeMenuBadges(
            /** @type {import("@web/env").OdooEnv} */ (
                /** @type {unknown} */ (this.env)
            ),
            this.displayedApps,
        );
    }

    _persistConfig() {
        return user.setUserSettings(
            "homemenu_config",
            serializeHomeMenuConfig(this.config),
        );
    }

    /** @param {HomeMenuApp} app */
    _togglePinned(app) {
        if (app.xmlid === undefined) {
            return;
        }
        const index = this.config.pinned.indexOf(app.xmlid);
        if (index === -1) {
            this.config.pinned.push(app.xmlid);
        } else {
            this.config.pinned.splice(index, 1);
        }
        this._persistConfig();
    }

    /** @param {HomeMenuApp} app */
    _toggleHidden(app) {
        if (app.xmlid === undefined) {
            return;
        }
        const index = this.config.hidden.indexOf(app.xmlid);
        if (index === -1) {
            this.config.hidden.push(app.xmlid);
            // A hidden app has no place to be pinned to.
            const pinnedIndex = this.config.pinned.indexOf(app.xmlid);
            if (pinnedIndex !== -1) {
                this.config.pinned.splice(pinnedIndex, 1);
            }
        } else {
            this.config.hidden.splice(index, 1);
        }
        this._persistConfig();
    }

    _resetLayout() {
        const defaults = this.defaultConfig;
        this.config.order = [...defaults.order];
        this.config.pinned = [...defaults.pinned];
        this.config.hidden = [...defaults.hidden];
        this.props.resetApps?.();
        // No layout of their own: the user follows the company's again.
        return user.setUserSettings("homemenu_config", null);
    }

    async _setCompanyDefault() {
        const config = JSON.parse(serializeHomeMenuConfig(this.config));
        await this.orm.write("res.company", [user.activeCompany.id], {
            homemenu_default_config: config,
        });
        session.homemenu_default_config = config;
        const defaults = this.defaultConfig;
        defaults.order = [...this.config.order];
        defaults.pinned = [...this.config.pinned];
        defaults.hidden = [...this.config.hidden];
        this.render();
    }

    _toggleEditing() {
        this.state.editing = !this.state.editing;
        this.state.focusedIndex = null;
    }

    /**
     * Update this.state.focusedIndex if not null.
     * @param {string} cmd
     */
    _updateFocusedIndex(cmd) {
        const nbrApps = this.visibleApps.length;
        const lastIndex = nbrApps - 1;
        const focusedIndex = this.state.focusedIndex;
        if (lastIndex < 0) {
            return;
        }
        this.focusSelectedTile = true;
        if (focusedIndex === null) {
            this.state.focusedIndex = 0;
            return;
        }
        const lineNumber = Math.ceil(nbrApps / this.maxIconNumber);
        const currentLine = Math.ceil((focusedIndex + 1) / this.maxIconNumber);
        let newIndex;
        switch (cmd) {
            case "previousColumn":
                if (focusedIndex % this.maxIconNumber) {
                    // app is not the first one on its line
                    newIndex = focusedIndex - 1;
                } else {
                    newIndex =
                        focusedIndex +
                        Math.min(lastIndex - focusedIndex, this.maxIconNumber - 1);
                }
                break;
            case "nextColumn":
                if (
                    focusedIndex === lastIndex ||
                    (focusedIndex + 1) % this.maxIconNumber === 0
                ) {
                    // app is the last one on its line
                    newIndex = (currentLine - 1) * this.maxIconNumber;
                } else {
                    newIndex = focusedIndex + 1;
                }
                break;
            case "previousLine":
                if (currentLine === 1) {
                    newIndex = focusedIndex + (lineNumber - 1) * this.maxIconNumber;
                    if (newIndex > lastIndex) {
                        newIndex = lastIndex;
                    }
                } else {
                    // we go to the previous line on same column
                    newIndex = focusedIndex - this.maxIconNumber;
                }
                break;
            case "nextLine":
                if (currentLine === lineNumber) {
                    newIndex = focusedIndex % this.maxIconNumber;
                } else {
                    // we go to the next line on the closest column
                    newIndex =
                        focusedIndex +
                        Math.min(this.maxIconNumber, lastIndex - focusedIndex);
                }
                break;
            default:
                return;
        }
        // if newIndex is out of bounds -> normalize it
        if (newIndex < 0) {
            newIndex = lastIndex;
        } else if (newIndex > lastIndex) {
            newIndex = 0;
        }
        this.state.focusedIndex = newIndex;
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
        this.config.order = order;
        this._persistConfig();
    }

    /** @param {import("@web/core/utils/dnd/sortable").SortableHandlerParams} params */
    _sortStart({ element, addClass }) {
        addClass(/** @type {HTMLElement} */ (element.children[0]), "o_dragged_app");
    }

    /** @param {HomeMenuApp} app */
    _onAppClick(app) {
        this._openMenu(app);
    }

    /** @param {number} index */
    _onAppFocus(index) {
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
            [
                "Escape",
                () =>
                    this.state.editing
                        ? this._toggleEditing()
                        : this.homeMenuService.toggle(false),
            ],
        ];
        for (const [hotkey, callback] of hotkeys) {
            useHotkey(hotkey, callback, { allowRepeat: true, isAvailable });
        }
        // A tile with the real focus is a link: Enter is its own click.
        useHotkey(
            "Enter",
            () => {
                const focusedIndex = this.state.focusedIndex;
                const menu =
                    focusedIndex === null ? undefined : this.visibleApps[focusedIndex];
                if (menu) {
                    this._openMenu(menu);
                }
            },
            {
                allowRepeat: true,
                isAvailable: (target) => isAvailable() && target === this.inputEl,
            },
        );
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
        const onClose = () => {
            this._focusInput();
            if (this.inputEl) {
                this.inputEl.value = "";
            }
        };
        const typed = this.compositionStart ? "" : (this.inputEl?.value.trim() ?? "");
        this.compositionStart = false;
        // A leading namespace character the palette knows is the user's
        // choice of namespace; anything else searches the menus.
        const isNamespace =
            typed.length > 0 && registry.category("command_setup").contains(typed[0]);
        const searchValue = isNamespace ? typed : `/${typed}`;
        this.command.openMainPalette(
            /** @type {any} */ ({ searchValue, FooterComponent }),
            onClose,
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
