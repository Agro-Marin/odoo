// @ts-check
/** @odoo-module native */

/** @module @web/core/hotkeys/hotkey_hook */

import { useEffect } from "@odoo/owl";
import { useService } from "@web/core/utils/hooks";
/**
 * @param {string} hotkey
 * @param {import("./hotkey_service").HotkeyCallback} callback
 * @param {import("./hotkey_service").HotkeyOptions} [options]
 */
export function useHotkey(hotkey, callback, options = {}) {
    const hotkeyService = useService("hotkey");
    useEffect(
        () => hotkeyService.add(hotkey, callback, options),
        () => [],
    );
}
