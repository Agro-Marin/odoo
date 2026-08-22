// @ts-check
/** @odoo-module native */

import { useEffect } from "@odoo/owl";
import { useActiveElementScope } from "@web/core/utils/active_element_scope";
import { useService } from "@web/core/utils/hooks";
/**
 * @param {string} hotkey
 * @param {import("./hotkey_service").HotkeyCallback} callback
 * @param {import("./hotkey_service").HotkeyOptions} [options]
 */
export function useHotkey(hotkey, callback, options = {}) {
    const hotkeyService = useService("hotkey");
    const scope = useActiveElementScope();
    useEffect(
        () => hotkeyService.add(hotkey, callback, { scope, ...options }),
        () => [],
    );
}
