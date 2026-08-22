// @ts-check
/** @odoo-module native */

import { useEffect } from "@odoo/owl";
import { useActiveElementScope } from "@web/core/utils/active_element_scope";
import { useService } from "@web/core/utils/hooks";
/** @import { CommandOptions } from "./command_service.js" */

/**
 * @param {string} name
 * @param {()=>(void | import("@web/ui/commands/command_palette").CommandPaletteConfig)} action
 * @param {CommandOptions} [options]
 */
export function useCommand(name, action, options = {}) {
    const commandService = useService("command");
    const scope = useActiveElementScope();
    useEffect(
        () => commandService.add(name, action, { scope, ...options }),
        () => [],
    );
}
