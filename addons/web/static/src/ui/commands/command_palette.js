// @ts-check
/** @odoo-module native */

/** @module @web/ui/commands/command_palette */

import {
    Component,
    EventBus,
    markRaw,
    onWillDestroy,
    onWillStart,
    useExternalListener,
    useRef,
    useState,
} from "@odoo/owl";
import { isMacOS, isMobileOS } from "@web/core/browser/feature_detection";
import { CommandPaletteEvent } from "@web/core/events";
import { useHotkey } from "@web/core/hotkeys/hotkey_hook";
import { _t } from "@web/core/translation";
import { KeepLast, Race } from "@web/core/utils/concurrency";
import { highlightText } from "@web/core/utils/dom/html";
import { scrollTo } from "@web/core/utils/dom/scrolling";
import { useAutofocus, useService } from "@web/core/utils/hooks";
import { fuzzyLookup } from "@web/core/utils/search";
import { debounce } from "@web/core/utils/timing";
import { Dialog } from "@web/ui/dialog/dialog";

/** @import { Command } from "./command_service.js" */

const DEFAULT_PLACEHOLDER = _t("Search...");
const DEFAULT_EMPTY_MESSAGE = _t("No result found");
const FUZZY_NAMESPACES = ["default"];

export const MAX_DISPLAYED_COMMANDS = 100;

/**
 * @typedef {Command & {
 *  Component?: import("@odoo/owl").ComponentConstructor;
 *  props?: object;
 * }} CommandItem
 */

/**
 * @typedef {{
 *  namespace?: string;
 *  provide: (env: any, options?: any) => CommandItem[] | Promise<CommandItem[]>;
 * }} Provider
 */

/**
 * @typedef {{
 *  categories: string[];
 *  debounceDelay: number;
 *  emptyMessage: string;
 *  placeholder: string;
 * }} NamespaceConfig
 */

/**
 * @typedef {{
 *  configByNamespace?: {[namespace: string]: NamespaceConfig};
 *  FooterComponent?: Component;
 *  providers: Provider[];
 *  searchValue?: string;
 * }} CommandPaletteConfig
 */

/**
 * @param {CommandItem[]} commands
 * @param {string[]} categories
 * @returns {Map<string, CommandItem[]>}
 */
function groupCommandsByCategory(commands, categories) {
    /** @type {Map<string, CommandItem[]>} */
    const byCategory = new Map(
        categories.map(
            (category) => /** @type {[string, CommandItem[]]} */ ([category, []]),
        ),
    );
    for (const command of commands) {
        const bucket =
            byCategory.get(/** @type {string} */ (command.category)) ??
            byCategory.get("default");
        bucket?.push(command);
    }
    return byCategory;
}

export class DefaultCommandItem extends Component {
    static template = "web.DefaultCommandItem";
    static props = {
        slots: { type: Object, optional: true },
        hotkey: { type: String, optional: true },
        hotkeyOptions: { type: String, optional: true },
        name: { type: String, optional: true },
        searchValue: { type: String, optional: true },
        executeCommand: { type: Function, optional: true },
    };
}

export class CommandPalette extends Component {
    static template = "web.CommandPalette";
    static components = { Dialog };
    static lastSessionId = 0;
    static props = {
        bus: { type: EventBus, optional: true },
        close: Function,
        config: Object,
    };

    // Declared here, assigned in setup() or in the methods below. Definite
    // assignment analysis credits only the constructor, so without these every
    // read would be `T | undefined`. Safe on an OWL Component, whose setup()
    // runs after construction — NOT on a Model, which calls setup() from its
    // own constructor and would be clobbered by a field initialiser.
    /** @type {number} */
    keyId;
    /** @type {Race<any>} */
    race;
    /** @type {KeepLast<PromiseSettledResult<CommandItem[]>[]>} */
    keepLast;
    /** @type {number} */
    _sessionId;
    /** @type {typeof DefaultCommandItem} */
    DefaultCommandItem;
    /** @type {Document | HTMLElement} */
    activeElement;
    /** @type {ReturnType<typeof useAutofocus>} */
    inputRef;
    /**
     * @type {{ commands: CommandItem[],
     *          emptyMessage: string,
     *          FooterComponent?: Component,
     *          hiddenCount: number,
     *          isLoading: boolean,
     *          namespace: string,
     *          placeholder: string,
     *          searchValue: string,
     *          selectedIndex: number }}
     */
    state;
    /** @type {ReturnType<typeof useRef>} */
    root;
    /** @type {ReturnType<typeof useRef>} */
    listboxRef;
    /** @type {Record<string, any>} */
    configByNamespace;
    /** @type {Record<string, Provider[]>} */
    providersByNamespace;
    /** @type {Promise<any> | null} */
    searchValuePromise;
    /** @type {string[]} */
    categoryKeys;
    /** @type {Record<string, string>} */
    categoryNames;
    /** @type {boolean} */
    mouseSelectionActive;
    /** @type {ReturnType<typeof debounce>} */
    lastDebounceSearch;

    setup() {
        if (this.props.bus) {
            const setConfig = (
                /** @type {{ detail: CommandPaletteConfig }} */ { detail },
            ) => this.setCommandPaletteConfig(detail);
            this.props.bus.addEventListener(CommandPaletteEvent.SET_CONFIG, setConfig);
            onWillDestroy(() =>
                this.props.bus.removeEventListener(
                    CommandPaletteEvent.SET_CONFIG,
                    setConfig,
                ),
            );
        }

        this.keyId = 1;
        this.race = new Race();
        this.keepLast = new KeepLast();
        this._sessionId = CommandPalette.lastSessionId++;
        this.DefaultCommandItem = DefaultCommandItem;
        this.activeElement = useService("ui").activeElement;
        this.inputRef = useAutofocus();

        useHotkey("Enter", () => this.executeSelectedCommand(), {
            bypassEditableProtection: true,
        });
        useHotkey("Control+Enter", () => this.executeSelectedCommand(true), {
            bypassEditableProtection: true,
        });
        useHotkey("ArrowUp", () => this.selectCommandAndScrollTo("PREV"), {
            bypassEditableProtection: true,
            allowRepeat: true,
        });
        useHotkey("ArrowDown", () => this.selectCommandAndScrollTo("NEXT"), {
            bypassEditableProtection: true,
            allowRepeat: true,
        });
        useExternalListener(window, "mousedown", this.onWindowMouseDown);

        this.state = useState(/** @type {any} */ ({}));

        this.root = useRef("root");
        this.listboxRef = useRef("listbox");

        onWillStart(() => this.setCommandPaletteConfig(this.props.config));
    }

    /** @returns {string} */
    get truncationMessage() {
        return _t("%s more results — refine your search", this.state.hiddenCount);
    }

    /** @returns {Array<{commands: CommandItem[], name: string, keyId: string}>} */
    get commandsByCategory() {
        const categories = [];
        const byCategory = groupCommandsByCategory(
            this.state.commands,
            this.categoryKeys,
        );
        for (const [category, commands] of byCategory) {
            if (commands.length) {
                categories.push({
                    commands,
                    name: this.categoryNames[category],
                    keyId: category,
                });
            }
        }
        return categories;
    }

    /**
     * @param {CommandPaletteConfig} config
     */
    async setCommandPaletteConfig(config) {
        this.configByNamespace = config.configByNamespace || {};
        this.state.FooterComponent = config.FooterComponent;

        this.providersByNamespace = /** @type {Record<string, Provider[]>} */ ({
            default: [],
        });
        for (const provider of config.providers) {
            const namespace = provider.namespace || "default";
            if (namespace in this.providersByNamespace) {
                this.providersByNamespace[namespace].push(provider);
            } else {
                this.providersByNamespace[namespace] = [provider];
            }
        }

        const { namespace, searchValue } = this.processSearchValue(
            config.searchValue || "",
        );
        this.switchNamespace(namespace);
        this.state.searchValue = searchValue;
        this.searchValuePromise = this.search(searchValue);
        await this.race.add(this.searchValuePromise);
    }

    /**
     * @param {string} namespace
     * @param {{ searchValue?: string, activeElement?: Element, sessionId?: number }} [options]
     */
    async setCommands(namespace, options = {}) {
        let categoryKeys = ["default"];
        /** @type {Record<string, string>} */
        let categoryNames = {};
        const proms = this.providersByNamespace[namespace].map(async (provider) =>
            provider.provide(this.env, options),
        );
        const settled = await this.keepLast.add(Promise.allSettled(proms));
        for (const result of settled) {
            if (result.status === "rejected") {
                console.error(
                    "Command palette: a command provider failed:",
                    result.reason,
                );
            }
        }
        let commands = /** @type {CommandItem[]} */ (
            settled
                .filter((result) => result.status === "fulfilled")
                .flatMap((result) => /** @type {any} */ (result).value)
        );
        const namespaceConfig = /** @type {any} */ (
            this.configByNamespace[namespace] || {}
        );
        if (options.searchValue && FUZZY_NAMESPACES.includes(namespace)) {
            commands = fuzzyLookup(options.searchValue, commands, (c) => c.name);
        } else {
            if (namespaceConfig.categories) {
                /** @type {CommandItem[]} */
                let commandsSorted = [];
                categoryKeys = [...namespaceConfig.categories];
                categoryNames = namespaceConfig.categoryNames || {};
                if (!categoryKeys.includes("default")) {
                    categoryKeys.push("default");
                }
                for (const bucket of groupCommandsByCategory(
                    commands,
                    categoryKeys,
                ).values()) {
                    commandsSorted = [...commandsSorted, ...bucket];
                }
                commands = commandsSorted;
            }
        }

        this.categoryKeys = categoryKeys;
        this.categoryNames = categoryNames;
        this.state.hiddenCount = Math.max(0, commands.length - MAX_DISPLAYED_COMMANDS);
        this.state.commands = markRaw(
            commands.slice(0, MAX_DISPLAYED_COMMANDS).map((command, index) => ({
                ...command,
                index,
                keyId: this.keyId++,
                text: highlightText(
                    options.searchValue ?? "",
                    command.name,
                    "fw-bolder text-primary",
                ),
            })),
        );
        this.selectCommand(this.state.commands.length ? 0 : -1);
        this.mouseSelectionActive = false;
        this.state.emptyMessage = (
            namespaceConfig.emptyMessage || DEFAULT_EMPTY_MESSAGE
        ).toString();
    }

    /**
     * @returns {CommandItem | null}
     */
    get selectedCommand() {
        return this.state.commands?.[this.state.selectedIndex] ?? null;
    }

    /**
     * @param {number} index
     */
    selectCommand(index) {
        const isSelectable =
            Number.isInteger(index) && index >= 0 && index < this.state.commands.length;
        this.state.selectedIndex = isSelectable ? index : -1;
    }

    /**
     * @param {"PREV" | "NEXT"} type
     */
    selectCommandAndScrollTo(type) {
        this.mouseSelectionActive = false;
        const index = this.state.selectedIndex;
        if (index === -1) {
            return;
        }
        const nextIndex =
            type === "NEXT"
                ? index < this.state.commands.length - 1
                    ? index + 1
                    : 0
                : index > 0
                  ? index - 1
                  : this.state.commands.length - 1;
        this.selectCommand(nextIndex);

        const listbox = this.listboxRef.el;
        const command = listbox?.querySelector(`#o_command_${nextIndex}`);
        if (listbox instanceof HTMLElement && command instanceof HTMLElement) {
            scrollTo(command, { scrollable: listbox });
        }
    }

    /**
     * @param {MouseEvent} event
     * @param {number} index
     */
    onCommandClicked(event, index) {
        event.preventDefault();
        this.selectCommand(index);
        const ctrlKey = isMacOS() ? event.metaKey : event.ctrlKey;
        this.executeSelectedCommand(ctrlKey);
    }

    /**
     * @param {CommandItem} command
     */
    async executeCommand(command) {
        let config;
        try {
            config = await command.action();
        } catch (error) {
            this.props.close();
            throw error;
        }
        if (config) {
            await this.setCommandPaletteConfig(config);
        } else {
            this.props.close();
        }
    }

    /**
     * @param {boolean} [ctrlKey]
     */
    async executeSelectedCommand(ctrlKey) {
        await this.searchValuePromise;
        const selectedCommand = this.selectedCommand;
        if (selectedCommand) {
            if (!ctrlKey) {
                await this.executeCommand(selectedCommand);
            } else if (selectedCommand.href) {
                window.open(selectedCommand.href, "_blank");
            }
        }
    }

    /**
     * @param {number} index
     */
    onCommandMouseEnter(index) {
        if (this.mouseSelectionActive) {
            this.selectCommand(index);
        } else {
            this.mouseSelectionActive = true;
        }
    }

    /**
     * @param {string} searchValue
     */
    async search(searchValue) {
        this.state.isLoading = true;
        try {
            await this.setCommands(this.state.namespace, {
                searchValue,
                activeElement: /** @type {Element} */ (this.activeElement),
                sessionId: this._sessionId,
            });
        } finally {
            this.state.isLoading = false;
        }
        if (this.inputRef.el) {
            this.inputRef.el.focus();
        }
    }

    /**
     * @param {string} value
     */
    debounceSearch(value) {
        const { namespace, searchValue } = this.processSearchValue(value);
        if (namespace !== "default" && this.state.namespace !== namespace) {
            this.switchNamespace(namespace);
        }
        this.state.searchValue = searchValue;
        this.searchValuePromise = this.lastDebounceSearch(searchValue).catch(() => {
            this.searchValuePromise = null;
        });
    }

    /**
     * @param {Event} ev
     */
    onSearchInput(ev) {
        this.debounceSearch(/** @type {HTMLInputElement} */ (ev.target).value);
    }

    /**
     * @param {KeyboardEvent} ev
     */
    onKeyDown(ev) {
        if (
            ev.key.toLowerCase() === "backspace" &&
            !(/** @type {HTMLInputElement} */ (ev.target).value.length) &&
            !ev.repeat
        ) {
            this.switchNamespace("default");
            this.state.searchValue = "";
            this.searchValuePromise = this.lastDebounceSearch("").catch(() => {
                this.searchValuePromise = null;
            });
        }
    }

    /**
     * @param {Event} ev
     */
    onWindowMouseDown(ev) {
        if (this.root.el && !this.root.el.contains(/** @type {Node} */ (ev.target))) {
            this.props.close();
        }
    }

    /**
     * @param {string} namespace
     */
    switchNamespace(namespace) {
        if (this.lastDebounceSearch) {
            this.lastDebounceSearch.cancel();
        }
        const namespaceConfig = /** @type {any} */ (
            this.configByNamespace[namespace] || {}
        );
        this.lastDebounceSearch = debounce(
            (/** @type {string} */ value) => this.search(value),
            namespaceConfig.debounceDelay || 0,
        );
        this.state.namespace = namespace;
        this.state.placeholder =
            namespaceConfig.placeholder || DEFAULT_PLACEHOLDER.toString();
    }

    /**
     * @param {string} searchValue
     * @returns {{ namespace: string, searchValue: string }}
     */
    processSearchValue(searchValue) {
        let namespace = "default";
        if (searchValue.length && this.providersByNamespace[searchValue[0]]) {
            namespace = searchValue[0];
            searchValue = searchValue.slice(1);
        }
        return { namespace, searchValue };
    }

    get isMacOS() {
        return isMacOS();
    }
    get isMobileOS() {
        return isMobileOS();
    }
}
