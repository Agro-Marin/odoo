// @ts-check
/** @odoo-module native */

/** @module @web/services/commands/command_hook - useCommand hook to register/unregister commands with component lifecycle */

import { useEffect } from "@odoo/owl";
import { useService } from "@web/core/utils/hooks";
/** @import { CommandOptions } from "./command_service.js" */

/**
 * Subscribes on mount, unsubscribes on unmount.
 * @param {string} name
 * @param {()=>(void | import("@web/services/commands/command_palette").CommandPaletteConfig)} action
 * @param {CommandOptions} [options]
 */
export function useCommand(name, action, options = {}) {
    const commandService = useService("command");
    useEffect(
        () => commandService.add(name, action, options),
        () => [],
    );
}
