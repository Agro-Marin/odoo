// @ts-check
/** @odoo-module native */

/** @module @web/core/browser/hotkeys - Pure keyboard event utilities (no service dependencies) */

import { isMacOS } from "@web/core/browser/feature_detection";

const ALPHANUM_KEYS = "abcdefghijklmnopqrstuvwxyz0123456789".split("");
const NAV_KEYS = [
    "arrowleft",
    "arrowright",
    "arrowup",
    "arrowdown",
    "pageup",
    "pagedown",
    "home",
    "end",
    "backspace",
    "enter",
    "tab",
    "delete",
    "space",
];
export const MODIFIERS = ["alt", "control", "shift"];
export const AUTHORIZED_KEYS = [...ALPHANUM_KEYS, ...NAV_KEYS, "escape", "<", ">"];

/**
 * Get the actual hotkey being pressed.
 *
 * @param {KeyboardEvent} ev
 * @returns {string} the active hotkey, in lowercase
 */
export function getActiveHotkey(ev) {
    if (!ev.key) {
        return "";
    }
    if (ev.isComposing) {
        return "";
    }
    const hotkey = [];

    if (isMacOS() ? ev.ctrlKey : ev.altKey) {
        hotkey.push("alt");
    }
    if (isMacOS() ? ev.metaKey : ev.ctrlKey) {
        hotkey.push("control");
    }
    if (ev.shiftKey) {
        hotkey.push("shift");
    }

    let key = ev.key.toLowerCase();

    if (key === " ") {
        key = "space";
    }

    if (!AUTHORIZED_KEYS.includes(key)) {
        if (ev.code?.startsWith("Digit")) {
            key = ev.code.slice(-1);
        } else if (ev.code?.startsWith("Key")) {
            key = ev.code.slice(-1).toLowerCase();
        }
    }
    if (!MODIFIERS.includes(key)) {
        hotkey.push(key);
    }

    return hotkey.join("+");
}
