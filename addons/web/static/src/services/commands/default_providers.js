// @ts-check
/** @odoo-module native */

/** @module @web/services/commands/default_providers - Default command palette providers: hotkey badges, clickable elements, setup registry */

import { Component } from "@odoo/owl";
import { isMacOS } from "@web/core/browser/feature_detection";
import { _t } from "@web/core/l10n/translation";
import { registry } from "@web/core/registry";
import { getVisibleElements } from "@web/core/utils/dom/ui";
import { capitalize } from "@web/core/utils/format/strings";
import { useHotkey } from "@web/services/hotkeys/hotkey_hook";

import { DefaultCommandItem } from "./command_palette.js";

const commandSetupRegistry = registry.category("command_setup");
commandSetupRegistry.add("default", {
    emptyMessage: _t("No command found"),
    placeholder: _t("Search for a command..."),
});

/**
 * Command palette item component that renders a hotkey badge and registers
 * the hotkey so the command can also be triggered by keyboard shortcut.
 */
export class HotkeyCommandItem extends Component {
    static template = "web.HotkeyCommandItem";
    static props = [
        "hotkey",
        "hotkeyOptions?",
        "name?",
        "searchValue?",
        "executeCommand",
        "slots",
    ];
    setup() {
        useHotkey(this.props.hotkey, this.props.executeCommand);
    }

    /**
     * Split a hotkey string into individual key labels, adapting modifier
     * names for macOS (Control→Command, Alt→Control).
     * @param {{ hotkey: string }} command
     * @returns {string[]} uppercase key labels
     */
    getKeysToPress(command) {
        const { hotkey } = command;
        let result = hotkey.split("+");
        if (isMacOS()) {
            result = result
                .map((x) => x.replace("control", "command"))
                .map((x) => x.replace("alt", "control"));
        }
        return result.map((key) => key.toUpperCase());
    }
}

const commandCategoryRegistry = registry.category("command_categories");
const commandProviderRegistry = registry.category("command_provider");
commandProviderRegistry.add("command", {
    provide: (env, options = {}) => {
        const commands = env.services.command
            .getCommands(options.activeElement)
            .map((/** @type {Record<string, any>} */ cmd) => ({
                // Copy — mutating cmd.category in place would rewrite the
                // registered command object.
                ...cmd,
                category: commandCategoryRegistry.contains(cmd.category)
                    ? cmd.category
                    : "default",
            }))
            .filter(
                (/** @type {Record<string, any>} */ command) =>
                    command.isAvailable === undefined || command.isAvailable(),
            );
        // Filter out same category dupplicate commands
        const uniqueCommands = commands.filter(
            (/** @type {Record<string, any>} */ obj, /** @type {number} */ index) =>
                index ===
                commands.findIndex(
                    (/** @type {Record<string, any>} */ o) =>
                        obj.name === o.name && obj.category === o.category,
                ),
        );
        return uniqueCommands.map((/** @type {Record<string, any>} */ command) => ({
            Component: command.hotkey ? HotkeyCommandItem : DefaultCommandItem,
            action: command.action,
            category: command.category,
            name: command.name,
            props: {
                hotkey: command.hotkey,
                hotkeyOptions: command.hotkeyOptions,
            },
        }));
    },
});

commandProviderRegistry.add("data-hotkeys", {
    provide: (env, options = {}) => {
        const commands = [];
        const overlayModifier = /** @type {any} */ (
            registry.category("services").get("hotkey")
        ).overlayModifier;
        // The hotkey service only replaces [accesskey] attrs by [data-hotkey]
        // on an overlay-modifier keypress: convert pending ones now so their
        // commands appear without requiring a prior ALT press. Scoped to the
        // UI active element, like the hotkey service's own takeover.
        for (const el of (options.activeElement ?? document).querySelectorAll(
            "[accesskey]",
        )) {
            if (el instanceof HTMLElement) {
                el.dataset.hotkey = el.accessKey;
                el.removeAttribute("accesskey");
            }
        }
        for (const el of getVisibleElements(
            options.activeElement,
            "[data-hotkey]:not(:disabled)",
        )) {
            const closest = /** @type {HTMLElement|null} */ (
                el.closest("[data-command-category]")
            );
            const category = closest ? closest.dataset.commandCategory : "default";
            if (category === "disabled") {
                continue;
            }

            const description =
                el.title ||
                el.dataset.bsOriginalTitle || // LEGACY: bootstrap moves title to data-bs-original-title
                el.dataset.tooltip ||
                /** @type {HTMLInputElement} */ (el).placeholder ||
                (el.innerText &&
                    `${el.innerText.slice(0, 50)}${el.innerText.length > 50 ? "..." : ""}`) ||
                _t("no description provided");

            commands.push({
                Component: HotkeyCommandItem,
                action: () => {
                    // AAB: not sure it is enough, we might need to trigger all events that occur when you actually click
                    el.focus();
                    el.click();
                },
                category,
                name: capitalize(description.trim().toLowerCase()),
                props: {
                    hotkey: `${overlayModifier}+${el.dataset.hotkey}`,
                },
            });
        }
        return commands;
    },
});
