// @ts-check
/** @odoo-module native */

import { useActiveElementScope } from "@web/core/utils/active_element_scope";
import { useService } from "@web/core/utils/hooks";
import { useLayoutEffect } from "@web/core/utils/layout_effect";

/** @import { CommandOptions } from "@web/ui/commands/command_service" */

/**
 * @param {string} name
 * @param {()=>(void | import("@web/ui/commands/command_palette").CommandPaletteConfig | Promise<void | import("@web/ui/commands/command_palette").CommandPaletteConfig>)} action
 * @param {CommandOptions} [options]
 */
export function useCommand(name, action, options = {}) {
    const commandService = useService("command");
    const scope = useActiveElementScope();
    useLayoutEffect(
        () => commandService.add(name, action, { scope, ...options }),
        () => [],
    );
}
