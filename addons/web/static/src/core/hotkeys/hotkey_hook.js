// @ts-check
/** @odoo-module native */

import { useActiveElementScope } from "@web/core/utils/active_element_scope";
import { useService } from "@web/core/utils/hooks";
import { useLayoutEffect } from "@web/core/utils/layout_effect";
/**
 * @param {string} hotkey
 * @param {import("./hotkey_service").HotkeyCallback} callback
 * @param {import("./hotkey_service").HotkeyOptions} [options]
 */
export function useHotkey(hotkey, callback, options = {}) {
    const hotkeyService = useService("hotkey");
    const scope = useActiveElementScope();
    useLayoutEffect(
        () => hotkeyService.add(hotkey, callback, { scope, ...options }),
        () => [],
    );
}
