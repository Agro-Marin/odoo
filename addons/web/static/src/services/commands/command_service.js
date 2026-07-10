// @ts-check
/** @odoo-module native */

/** @module @web/services/commands/command_service - Service that registers, manages, and opens the command palette */

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

// Each provider exposes `provide(env, options?)` which returns an array of
// commands; `namespace` (default "default") routes the provider to a palette.
commandProviderRegistry.addValidation({
    provide: Function,
    namespace: { type: String, optional: true },
    "*": true,
});

// Categories group commands inside a palette. Most entries are empty objects
// used purely as ordering anchors via the registry's `sequence` option.
// `namespace` opts a category into a non-default palette ("/", "?", "@").
commandCategoryRegistry.addValidation({
    namespace: { type: String, optional: true },
    name: { type: [String, Object], optional: true },
    "*": true,
});

// Per-namespace palette configuration (placeholder text, debounce, footer).
// All fields are optional: a missing entry just falls back to defaults.
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
        /** @type {Function | undefined} the latest opener/reconfigurer's onClose */
        let currentOnClose;
        const bus = new EventBus();

        hotkeyService.add("control+k", openMainPalette, {
            bypassEditableProtection: true,
            global: true,
        });

        /**
         * @param {CommandPaletteConfig} config command palette config merged with default config
         * @param {Function} onClose called when the command palette is closed
         * @returns the actual command palette config if the command palette is already open
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
         * @param {Function} onClose called when the command palette is closed
         */
        function openPalette(config, onClose) {
            if (isPaletteOpened) {
                // Reconfiguring an open palette adopts the new caller's
                // onClose too — otherwise its cleanup (focus restore, input
                // reset) silently never runs when the palette closes.
                if (onClose) {
                    currentOnClose = onClose;
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
                        if (currentOnClose) {
                            currentOnClose();
                        }
                    },
                },
            );
        }

        /**
         * @param {Command} command
         * @param {CommandOptions} options
         * @returns {number} token
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
                // Due to the way elements are mounted in the DOM by Owl (bottom-to-top),
                // we need to wait the next micro task tick to set the context activate
                // element of the subscription.
                queueMicrotask(() => {
                    registration.activeElement = ui.activeElement;
                });
            }

            return token;
        }

        /**
         * Unsubscribes the token corresponding subscription.
         *
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
             * @param {HTMLElement} activeElement
             * @returns {Command[]}
             */
            getCommands(activeElement) {
                const commands = [...registeredCommands.values()].filter(
                    (command) =>
                        command.activeElement === activeElement || command.global,
                );
                // Disambiguate same-name commands carrying distinct
                // ``identifier``s (e.g. two "Assign to me" fields on one
                // view) at read time: registrations are never renamed, so
                // names heal when one of the clashing commands unregisters.
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
        };
    },
};

registry.category("services").add("command", /** @type {any} */ (commandService));
