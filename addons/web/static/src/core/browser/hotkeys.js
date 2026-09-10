// @ts-check
/** @odoo-module native */

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
export const AUTHORIZED_KEY_SET = new Set(AUTHORIZED_KEYS);

const MODIFIER_KEYS = new Set([
    ...MODIFIERS,
    "meta",
    "altgraph",
    "capslock",
    "numlock",
    "scrolllock",
    "fn",
    "fnlock",
    "hyper",
    "super",
    "symbol",
    "symbollock",
    "os",
]);

/**
 * @param {KeyboardEvent | MouseEvent} ev
 * @returns {boolean} the platform's primary modifier: Cmd on macOS, Ctrl elsewhere
 */
export function isCtrlOrCmdKey(ev) {
    return isMacOS() ? ev.metaKey : ev.ctrlKey;
}

/**
 * @param {KeyboardEvent} ev
 * @returns {string}
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
    if (isCtrlOrCmdKey(ev)) {
        hotkey.push("control");
    }
    if (ev.shiftKey) {
        hotkey.push("shift");
    }

    let key = ev.key.toLowerCase();

    if (key === " ") {
        key = "space";
    }

    const composing = isMacOS() ? ev.altKey : ev.altKey && ev.ctrlKey;
    if (!AUTHORIZED_KEY_SET.has(key) && !composing) {
        if (ev.code?.startsWith("Digit")) {
            key = ev.code.slice(-1);
        } else if (ev.code?.startsWith("Key")) {
            key = ev.code.slice(-1).toLowerCase();
        }
    }
    if (!MODIFIER_KEYS.has(key)) {
        hotkey.push(key);
    }

    return hotkey.join("+");
}

/**
 * @param {KeyboardEvent} ev
 * @returns {boolean}
 */
export function isActivationKey(ev) {
    return ev.key === "Enter" || ev.key === " ";
}

/** @param {ParentNode} root */
export function adoptAccessKeys(root) {
    for (const el of root.querySelectorAll("[accesskey]")) {
        if (el instanceof HTMLElement) {
            el.dataset.hotkey = el.accessKey;
            el.removeAttribute("accesskey");
        }
    }
}
