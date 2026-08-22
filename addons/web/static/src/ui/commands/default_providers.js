// @ts-check
/** @odoo-module native */

import { Component } from "@odoo/owl";
import { isMacOS } from "@web/core/browser/feature_detection";
import { adoptAccessKeys } from "@web/core/browser/hotkeys";
import { useHotkey } from "@web/core/hotkeys/hotkey_hook";
import { registry } from "@web/core/registry";
import { _t } from "@web/core/translation";
import { getVisibleElements } from "@web/core/utils/dom/ui";
import { capitalize } from "@web/core/utils/format/strings";

import { COMMAND_ITEM_PROPS, DefaultCommandItem } from "./command_palette.js";

const commandSetupRegistry = registry.category("command_setup");
commandSetupRegistry.add("default", {
    emptyMessage: _t("No command found"),
    placeholder: _t("Search for a command..."),
});

export class HotkeyCommandItem extends Component {
    static template = "web.HotkeyCommandItem";
    static props = {
        ...COMMAND_ITEM_PROPS,
        hotkey: { type: String },
        hotkeyOptions: { type: Object, optional: true },
    };
    setup() {
        useHotkey(this.props.hotkey, this.props.executeCommand);
    }

    /**
     * @returns {string[]}
     */
    get keysToPress() {
        let result = this.props.hotkey.split("+");
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
                ...cmd,
                category: commandCategoryRegistry.contains(cmd.category)
                    ? cmd.category
                    : "default",
            }))
            .filter(
                (/** @type {Record<string, any>} */ command) =>
                    command.isAvailable === undefined || command.isAvailable(),
            );
        /** @type {Map<any, Set<any>>} */
        const seen = new Map();
        const uniqueCommands = commands.filter(
            (/** @type {Record<string, any>} */ command) => {
                let categories = seen.get(command.name);
                if (!categories) {
                    categories = new Set();
                    seen.set(command.name, categories);
                }
                if (categories.has(command.category)) {
                    return false;
                }
                categories.add(command.category);
                return true;
            },
        );
        return uniqueCommands.map((/** @type {Record<string, any>} */ command) => ({
            Component: command.hotkey ? HotkeyCommandItem : DefaultCommandItem,
            action: command.action,
            category: command.category,
            name: command.name,
            href: command.href,
            className: command.className,
            props: command.hotkey
                ? { hotkey: command.hotkey, hotkeyOptions: command.hotkeyOptions }
                : {},
        }));
    },
});

commandProviderRegistry.add("data-hotkeys", {
    provide: (env, options = {}) => {
        const commands = [];
        const overlayModifier = /** @type {any} */ (env.services.hotkey)
            .overlayModifier;
        adoptAccessKeys(options.activeElement ?? document);
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
                el.dataset.bsOriginalTitle ||
                el.dataset.tooltip ||
                /** @type {HTMLInputElement} */ (el).placeholder ||
                (el.innerText &&
                    `${el.innerText.slice(0, 50)}${el.innerText.length > 50 ? "..." : ""}`) ||
                _t("no description provided");

            commands.push({
                Component: HotkeyCommandItem,
                action: () => {
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
