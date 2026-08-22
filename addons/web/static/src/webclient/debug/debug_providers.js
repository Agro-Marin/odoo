// @ts-check
/** @odoo-module native */

import { registry } from "@web/core/registry";
import { _t } from "@web/core/translation";

import {
    enterDebugMode,
    enterDebugModeWithAssets,
    leaveDebugMode,
    openUnitTests,
    unitTestsLabel,
} from "./debug_affordances.js";
const commandProviderRegistry = registry.category("command_provider");

commandProviderRegistry.add("debug", {
    /**
     * @param {import("@web/env").OdooEnv} env
     * @param {{ searchValue: string }} options
     * @returns {import("@web/ui/commands/command_service").Command[]}
     */
    provide: (env, options) => {
        const result = [];
        if (env.debug) {
            if (!env.debug.includes("assets")) {
                result.push({
                    action: enterDebugModeWithAssets,
                    category: "debug",
                    name: _t("Activate debug mode (with assets)"),
                });
            }
            result.push({
                action: leaveDebugMode,
                category: "debug",
                name: _t("Deactivate debug mode"),
            });
            result.push({
                action: openUnitTests,
                category: "debug",
                name: unitTestsLabel(),
            });
        } else {
            const debugKey = "debug";
            if (options.searchValue.toLowerCase() === debugKey) {
                result.push({
                    action: enterDebugMode,
                    category: "debug",
                    name: `${_t("Activate debug mode")} (${debugKey})`,
                });
                result.push({
                    action: enterDebugModeWithAssets,
                    category: "debug",
                    name: `${_t("Activate debug mode (with assets)")} (${debugKey})`,
                });
            }
        }
        return result;
    },
});
