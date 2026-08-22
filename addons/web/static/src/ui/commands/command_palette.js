// @ts-check
/** @odoo-module native */

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
import { browser } from "@web/core/browser/browser";
import { isMacOS, isMobileOS } from "@web/core/browser/feature_detection";
import { reportUncaught } from "@web/core/errors/error_utils";
import { CommandPaletteEvent } from "@web/core/events";
import { useHotkey } from "@web/core/hotkeys/hotkey_hook";
import { _t } from "@web/core/translation";
import { ErrorHandler } from "@web/core/utils/components";
import { KeepLast, Race } from "@web/core/utils/concurrency";
import { highlightText } from "@web/core/utils/dom/html";
import { scrollTo } from "@web/core/utils/dom/scrolling";
import { useAutofocus, useChildRef, useService } from "@web/core/utils/hooks";
import { fuzzyLookup } from "@web/core/utils/search";
import { debounce } from "@web/core/utils/timing";
import { Dialog } from "@web/ui/dialog/dialog";

/** @import { Command } from "./command_service.js" */

const DEFAULT_PLACEHOLDER = _t("Search...");
const DEFAULT_EMPTY_MESSAGE = _t("No result found");
const FUZZY_NAMESPACES = ["default"];

export const MAX_DISPLAYED_COMMANDS = 100;

/**
 * @type {WeakMap<object, Set<string>>}
 */
const BROKEN_COMMANDS = new WeakMap();

/**
 * @type {WeakMap<Function, number>}
 */
const COMPONENT_IDS = new WeakMap();
let nextComponentId = 1;

/**
 * @param {Function} [component]
 * @returns {string}
 */
function componentId(component) {
    if (!component) {
        return "";
    }
    let id = COMPONENT_IDS.get(component);
    if (id === undefined) {
        id = nextComponentId++;
        COMPONENT_IDS.set(component, id);
    }
    return String(id);
}

/**
 * @param {CommandItem} command
 * @returns {string}
 */
function commandKey(command) {
    const props = /** @type {Record<string, any>} */ (command.props ?? {});
    const propSignature = Object.keys(props)
        .sort()
        .map((name) => {
            const value = props[name];
            const isCarrier =
                typeof value === "function" ||
                (value !== null && typeof value === "object");
            return isCarrier ? name : `${name}=${String(value)}`;
        })
        .join("\u0000");
    return [
        command.category ?? "",
        command.name,
        componentId(command.Component),
        propSignature,
    ].join("\u0000");
}

/**
 * @typedef {Command & {
 * Component?: import("@odoo/owl").ComponentConstructor;
 * props?: object;
 * }} CommandItem
 */

/**
 * @typedef {CommandItem & {
 * index: number;
 * keyId: number;
 * text: string | ReturnType<typeof highlightText>;
 * }} DisplayedCommand
 */

/**
 * @typedef {{
 * namespace?: string;
 * provide: (env: any, options?: any) => CommandItem[] | Promise<CommandItem[]>;
 * }} Provider
 */

/**
 * @typedef {{
 * categories: string[];
 * debounceDelay: number;
 * emptyMessage: string;
 * placeholder: string;
 * }} NamespaceConfig
 */

/**
 * @typedef {{
 * configByNamespace?: {[namespace: string]: NamespaceConfig};
 * FooterComponent?: Component;
 * providers: Provider[];
 * searchValue?: string;
 * }} CommandPaletteConfig
 */

/**
 * @template {CommandItem} T
 * @param {T[]} commands
 * @param {string[]} categories
 * @returns {Map<string, T[]>}
 */
function groupCommandsByCategory(commands, categories) {
    /** @type {Map<string, T[]>} */
    const byCategory = new Map(
        categories.map((category) => /** @type {[string, T[]]} */ ([category, []])),
    );
    for (const command of commands) {
        const bucket =
            byCategory.get(/** @type {string} */ (command.category)) ??
            byCategory.get("default");
        bucket?.push(command);
    }
    return byCategory;
}

/**
 * @type {Record<string, any>}
 */
export const COMMAND_ITEM_PROPS = {
    slots: { type: Object, optional: true },
    name: { type: String, optional: true },
    searchValue: { type: String, optional: true },
    executeCommand: { type: Function, optional: true },
};

export class DefaultCommandItem extends Component {
    static template = "web.DefaultCommandItem";
    static props = { ...COMMAND_ITEM_PROPS };
}

export class CommandPalette extends Component {
    static template = "web.CommandPalette";
    static components = { Dialog, ErrorHandler };
    static lastSessionId = 0;
    static props = {
        bus: { type: EventBus, optional: true },
        close: Function,
        config: Object,
    };

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
     * @type {{ commands: DisplayedCommand[],
     * emptyMessage: string,
     * FooterComponent?: Component,
     * hiddenCount: number,
     * isLoading: boolean,
     * namespace: string,
     * placeholder: string,
     * revision: number,
     * searchValue: string,
     * selectedIndex: number }}
     */
    state;
    /** @type {ReturnType<typeof useRef>} */
    root;
    /** @type {ReturnType<typeof useRef>} */
    listboxRef;
    /** @type {ReturnType<typeof useChildRef>} */
    modalRef;
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
    /** @type {Set<string>} */
    brokenCommands;

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
        this.adoptBrokenCommandsOf(this.props.config);
        this.race = new Race();
        this.keepLast = new KeepLast();
        this._sessionId = CommandPalette.lastSessionId++;
        this.DefaultCommandItem = DefaultCommandItem;
        this.activeElement = useService("ui").activeElement;
        this.inputRef = useAutofocus();

        this.modalRef = useChildRef();
        /** @type {import("@web/core/hotkeys/hotkey_service").HotkeyOptions} */
        const inPalette = {
            bypassEditableProtection: true,
            scope: () => this.modalRef.el,
        };

        useHotkey("Enter", () => this.executeSelectedCommand(), inPalette);
        useHotkey("Control+Enter", () => this.executeSelectedCommand(true), inPalette);
        useHotkey("ArrowUp", () => this.selectCommandAndScrollTo("PREV"), {
            ...inPalette,
            allowRepeat: true,
        });
        useHotkey("ArrowDown", () => this.selectCommandAndScrollTo("NEXT"), {
            ...inPalette,
            allowRepeat: true,
        });
        useExternalListener(window, "mousedown", this.onWindowMouseDown);

        /**
         * @type {{
         * commands: any[];
         * namespace: string;
         * searchValue: string;
         * placeholder: string;
         * emptyMessage: string;
         * hiddenCount: number;
         * selectedIndex: number;
         * isLoading: boolean;
         * revision: number;
         * FooterComponent: any;
         * }}
         */
        this.state = useState({
            commands: [],
            namespace: "default",
            searchValue: "",
            placeholder: "",
            emptyMessage: "",
            hiddenCount: 0,
            selectedIndex: -1,
            isLoading: false,
            revision: 0,
            FooterComponent: undefined,
        });

        /** @type {string[]} */
        this.categoryKeys = ["default"];
        /** @type {Record<string, string>} */
        this.categoryNames = {};

        this.root = useRef("root");
        this.listboxRef = useRef("listbox");

        onWillStart(() => this.setCommandPaletteConfig(this.props.config));
    }

    /** @returns {string} */
    get truncationMessage() {
        return _t("%s more results — refine your search", this.state.hiddenCount);
    }

    /** @returns {Array<{commands: DisplayedCommand[], name: string, keyId: string}>} */
    get commandsByCategory() {
        void this.state.revision;
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
    adoptBrokenCommandsOf(config) {
        this.brokenCommands = BROKEN_COMMANDS.get(config) ?? new Set();
        BROKEN_COMMANDS.set(config, this.brokenCommands);
    }

    /**
     * @param {CommandPaletteConfig} config
     */
    async setCommandPaletteConfig(config) {
        this.adoptBrokenCommandsOf(config);
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

        if (this.brokenCommands.size) {
            commands = commands.filter(
                (command) => !this.brokenCommands.has(commandKey(command)),
            );
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
     * @param {DisplayedCommand} command
     * @param {Error} error
     */
    handleCommandError(command, error) {
        const key = commandKey(command);
        if (this.brokenCommands.has(key)) {
            return;
        }
        this.brokenCommands.add(key);
        const position = this.state.commands.indexOf(command);
        if (position !== -1) {
            this.state.commands.splice(position, 1);
            this.state.commands.forEach((c, index) => {
                c.index = index;
            });
            this.selectCommand(this.state.commands.length ? 0 : -1);
            this.state.revision++;
        }
        reportUncaught(error);
    }

    /**
     * @returns {DisplayedCommand | null}
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
                browser.open(selectedCommand.href, "_blank");
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
        this.searchValuePromise = this.trackSearch(
            this.lastDebounceSearch(searchValue),
        );
    }

    /**
     * @param {Promise<any>} promise
     * @returns {Promise<any>}
     */
    trackSearch(promise) {
        const tracked = promise.catch(() => {
            if (this.searchValuePromise === tracked) {
                this.searchValuePromise = null;
            }
        });
        return tracked;
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
            this.searchValuePromise = this.trackSearch(this.lastDebounceSearch(""));
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
        this.state.placeholder = (
            namespaceConfig.placeholder || DEFAULT_PLACEHOLDER
        ).toString();
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
