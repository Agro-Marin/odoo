// @ts-check
/** @odoo-module native */

/** @module @web/services/commands/command_service */

import { Component, EventBus } from "@odoo/owl";
import { CommandPaletteEvent } from "@web/core/events";
import { registry } from "@web/core/registry";

import { CommandPalette } from "./command_palette.js";
/** @import { CommandPaletteConfig } from "./command_palette.js" */
/** @import { HotkeyOptions } from "../hotkeys/hotkey_service.js" */

/**
 * @typedef {{
 *  name: string;
 *  action: ()=>(void | CommandPaletteConfig);
 *  category?: string;
 *  href?: string;
 *  className?: string;
 * }} Command
 */

/**
 * @typedef {{
 *  category?: string;
 *  isAvailable?: (...args: any[]) => boolean;
 *  global?: boolean;
 *  hotkey?: string;
 *  hotkeyOptions?: HotkeyOptions
 * }} CommandOptions
 */

/**
 * @typedef {Command & CommandOptions & {
 *  identifier?: string;
 *  activeElement?: HTMLElement;
 *  removeHotkey?: ()=>void;
 * }} CommandRegistration
 */

const commandCategoryRegistry = registry.category("command_categories");
const commandProviderRegistry = registry.category("command_provider");
const commandSetupRegistry = registry.category("command_setup");

commandProviderRegistry.addValidation({
    provide: Function,
    namespace: { type: String, optional: true },
    "*": true,
});

commandCategoryRegistry.addValidation({
    namespace: { type: String, optional: true },
    name: { type: [String, Object], optional: true },
    "*": true,
});

commandSetupRegistry.addValidation({
    debounceDelay: { type: Number, optional: true },
    emptyMessage: { type: [String, Object], optional: true },
    name: { type: [String, Object], optional: true },
    placeholder: { type: [String, Object], optional: true },
    "*": true,
});

class DefaultFooter extends Component {
    static template = "web.DefaultFooter";
    static props = {
        switchNamespace: { type: Function },
    };
    setup() {
        this.elements = commandSetupRegistry
            .getEntries()
            .map((el) => ({ namespace: el[0], name: el[1].name }))
            .filter((el) => el.name);
    }

    onClick(/** @type {string} */ namespace) {
        this.props.switchNamespace(namespace);
    }
}

export const commandService = {
    dependencies: ["dialog", "hotkey", "ui"],
    /**
     * @param {import("@web/env").OdooEnv} env
     * @param {{ dialog: any, hotkey: any, ui: any }} services
     */
    start(env, { dialog, hotkey: hotkeyService, ui }) {
        /** @type {Map<number, CommandRegistration>} */
        const registeredCommands = new Map();
        let nextToken = 0;
        let isPaletteOpened = false;
        /** @type {Function | undefined} */
        let currentOnClose;
        const bus = new EventBus();

        const removeMainPaletteHotkey = hotkeyService.add(
            "control+k",
            () => openMainPalette(),
            {
                bypassEditableProtection: true,
                global: true,
            },
        );

        /**
         * @param {CommandPaletteConfig} [config]
         * @param {Function} [onClose]
         */
        function openMainPalette(config = /** @type {any} */ ({}), onClose) {
            /** @type {Record<string, any>} */
            const configByNamespace = {};
            for (const provider of commandProviderRegistry.getAll()) {
                const namespace = provider.namespace || "default";
                if (!configByNamespace[namespace]) {
                    configByNamespace[namespace] = {
                        categories: [],
                        categoryNames: {},
                    };
                }
            }

            for (const [category, el] of commandCategoryRegistry.getEntries()) {
                const namespace = el.namespace || "default";
                const name = el.name;
                if (namespace in configByNamespace) {
                    configByNamespace[namespace].categories.push(category);
                    configByNamespace[namespace].categoryNames[category] = name;
                }
            }

            for (const [
                namespace,
                { emptyMessage, debounceDelay, placeholder },
            ] of commandSetupRegistry.getEntries()) {
                if (namespace in configByNamespace) {
                    if (emptyMessage) {
                        configByNamespace[namespace].emptyMessage = emptyMessage;
                    }
                    if (debounceDelay !== undefined) {
                        configByNamespace[namespace].debounceDelay = debounceDelay;
                    }
                    if (placeholder) {
                        configByNamespace[namespace].placeholder = placeholder;
                    }
                }
            }

            config = Object.assign(
                {
                    configByNamespace,
                    FooterComponent: DefaultFooter,
                    providers: commandProviderRegistry.getAll(),
                },
                config,
            );
            return openPalette(config, onClose);
        }

        /**
         * @param {CommandPaletteConfig} config
         * @param {Function} [onClose]
         */
        function openPalette(config, onClose) {
            if (isPaletteOpened) {
                if (onClose) {
                    const previousOnClose = currentOnClose;
                    currentOnClose = () => {
                        try {
                            previousOnClose?.();
                        } finally {
                            onClose();
                        }
                    };
                }
                bus.trigger(CommandPaletteEvent.SET_CONFIG, config);
                return;
            }

            isPaletteOpened = true;
            currentOnClose = onClose;
            dialog.add(
                CommandPalette,
                {
                    config,
                    bus,
                },
                {
                    onClose: () => {
                        isPaletteOpened = false;
                        const onCloseCallback = currentOnClose;
                        currentOnClose = undefined;
                        onCloseCallback?.();
                    },
                },
            );
        }

        /**
         * @param {Command} command
         * @param {CommandOptions} options
         * @returns {number}
         */
        function registerCommand(command, options) {
            if (
                !command.name ||
                !command.action ||
                typeof command.action !== "function"
            ) {
                throw new Error("A Command must have a name and an action function.");
            }
            /** @type {CommandRegistration} */
            const registration = /** @type {any} */ ({
                ...command,
                ...options,
            });
            if (registration.hotkey) {
                const action = async () => {
                    const commandService = /** @type {any} */ (env.services.command);
                    const config = await command.action();
                    if (!isPaletteOpened && config) {
                        commandService.openPalette(config);
                    }
                };
                registration.removeHotkey = hotkeyService.add(
                    registration.hotkey,
                    action,
                    {
                        ...options.hotkeyOptions,
                        global: registration.global,
                        isAvailable: (/** @type {any[]} */ ...args) => {
                            let available = true;
                            if (registration.isAvailable) {
                                available = registration.isAvailable(...args);
                            }
                            if (available && options.hotkeyOptions?.isAvailable) {
                                available = options.hotkeyOptions?.isAvailable(
                                    .../** @type {[any]} */ (args),
                                );
                            }
                            return available;
                        },
                    },
                );
            }

            const token = nextToken++;
            registeredCommands.set(token, registration);
            if (!(/** @type {any} */ (options).activeElement)) {
                queueMicrotask(() => {
                    registration.activeElement = ui.activeElement;
                });
            }

            return token;
        }

        /**
         * @param {number} token
         */
        function unregisterCommand(token) {
            const cmd = registeredCommands.get(token);
            if (cmd?.removeHotkey) {
                cmd.removeHotkey();
            }
            registeredCommands.delete(token);
        }

        return {
            /**
             * @param {string} name
             * @param {()=>(void | CommandPaletteConfig)} action
             * @param {CommandOptions} [options]
             * @returns {() => void}
             */
            add(name, action, options = {}) {
                const token = registerCommand({ name, action }, options);
                return () => {
                    unregisterCommand(token);
                };
            },
            /**
             * @param {Document | HTMLElement} activeElement
             * @returns {Command[]}
             */
            getCommands(activeElement) {
                const commands = [...registeredCommands.values()].filter(
                    (command) =>
                        command.activeElement === activeElement || command.global,
                );
                /** @type {Map<string, CommandRegistration[]>} */
                const byName = new Map();
                for (const command of commands) {
                    if (command.identifier) {
                        const group = byName.get(command.name);
                        if (group) {
                            group.push(command);
                        } else {
                            byName.set(command.name, [command]);
                        }
                    }
                }
                return commands.map((command) => {
                    const group = command.identifier && byName.get(command.name);
                    if (
                        group &&
                        group.length > 1 &&
                        group.some((c) => c.identifier !== command.identifier)
                    ) {
                        return {
                            ...command,
                            name: `${command.name} (${command.identifier})`,
                        };
                    }
                    return command;
                });
            },
            openMainPalette,
            openPalette,
            destroy() {
                removeMainPaletteHotkey();
                for (const token of [...registeredCommands.keys()]) {
                    unregisterCommand(token);
                }
                currentOnClose = undefined;
                isPaletteOpened = false;
            },
        };
    },
};

registry.category("services").add("command", /** @type {any} */ (commandService));
