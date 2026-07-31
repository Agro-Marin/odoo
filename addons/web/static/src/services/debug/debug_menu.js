// @ts-check
/** @odoo-module native */

/** @module @web/services/debug/debug_menu */

import { Dropdown } from "@web/components/dropdown/dropdown";
import { DropdownItem } from "@web/components/dropdown/dropdown_item";
import { _t } from "@web/core/l10n/translation";
import { useService } from "@web/core/utils/hooks";
import { useCommand } from "@web/services/commands/command_hook";
import { DebugMenuBasic } from "@web/services/debug/debug_menu_basic";

import { useEnvDebugContext } from "./debug_context.js";

export class DebugMenu extends DebugMenuBasic {
    static components = { Dropdown, DropdownItem };
    static props = {};
    setup() {
        super.setup();
        const debugContext = useEnvDebugContext();
        this.command = useService("command");
        useCommand(
            _t("Debug tools..."),
            /** @type {any} */ (
                async () => {
                    const items = await debugContext.getItems(
                        /** @type {import("@web/env").OdooEnv} */ (this.env),
                    );
                    const provider = {
                        async provide() {
                            /** @type {{ name: string, action: any }[]} */
                            const result = [];
                            for (const item of items) {
                                if (item.type === "item") {
                                    result.push({
                                        name: item.description.toString(),
                                        action: item.callback,
                                    });
                                }
                            }
                            return result;
                        },
                    };
                    const configByNamespace = {
                        default: {
                            emptyMessage: _t("No debug command found"),
                            placeholder: _t("Choose a debug command..."),
                        },
                    };
                    const commandPaletteConfig = {
                        configByNamespace,
                        providers: [provider],
                    };
                    return commandPaletteConfig;
                }
            ),
            {
                category: "debug",
            },
        );
    }
}
