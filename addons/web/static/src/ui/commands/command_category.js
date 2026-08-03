// @ts-check
/** @odoo-module native */

/**
 * @module @web/ui/commands/command_category
 */

/** @type {import("@web/core/registry").Registry<any>} */
import { registry } from "@web/core/registry";
const commandCategoryRegistry = registry.category("command_categories");
commandCategoryRegistry
    .add("app", {}, { sequence: 10 })
    .add("smart_action", {}, { sequence: 15 })
    .add("actions", {}, { sequence: 30 })
    .add("default", {}, { sequence: 50 })
    .add("view_switcher", {}, { sequence: 100 })
    .add("debug", {}, { sequence: 110 })
    .add("disabled", {});
