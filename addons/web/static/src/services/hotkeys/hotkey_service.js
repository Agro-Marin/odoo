// @ts-check
/** @odoo-module native */

/** @module @web/services/hotkeys/hotkey_service */

import { browser } from "@web/core/browser/browser";
import {
    adoptAccessKeys,
    AUTHORIZED_KEYS,
    getActiveHotkey,
    MODIFIERS,
} from "@web/core/browser/hotkeys";
import { registry } from "@web/core/registry";
import { getVisibleElements } from "@web/core/utils/dom/ui";

export { getActiveHotkey };

/**
 * @typedef {(context: { area: HTMLElement, target: EventTarget }) => void} HotkeyCallback
 * @typedef {Object} HotkeyOptions
 * @property {boolean} [allowRepeat]
 * @property {boolean} [bypassEditableProtection]
 * @property {boolean} [global]
 * @property {() => HTMLElement} [area]
 * @property {(target: HTMLElement) => boolean} [isAvailable]
 * @property {() => HTMLElement} [withOverlay]
 * @typedef {HotkeyOptions & {
 *  hotkey: string,
 *  callback: HotkeyCallback,
 *  activeElement: HTMLElement | null,
 * }} HotkeyRegistration
 */

export const hotkeyService = {
    dependencies: ["ui"],
    overlayModifier: "alt",
    /**
     * @param {import("@web/env").OdooEnv} env
     * @param {{ ui: any }} services
     */
    start(env, { ui }) {
        /** @type {Map<number, HotkeyRegistration>} */
        const registrations = new Map();
        /**
         * @type {Map<string, Set<HotkeyRegistration>>}
         */
        const registrationsByHotkey = new Map();
        let nextToken = 0;
        let overlaysVisible = false;

        /**
         * @param {string} hotkey
         * @returns {boolean}
         */
        function includesOverlayModifier(hotkey) {
            return hotkeyService.overlayModifier
                .split("+")
                .every((part) => hotkey.includes(part));
        }

        /** @type {Set<() => void>} */
        const listenerRemovers = new Set();
        const removeWindowListeners = addListeners(/** @type {any} */ (browser));

        /**
         * @param {Window} target
         * @returns {() => void}
         */
        function addListeners(target) {
            target.addEventListener("keydown", onKeydown);
            target.addEventListener("keyup", removeHotkeyOverlays);
            target.addEventListener("blur", removeHotkeyOverlays);
            target.addEventListener("click", removeHotkeyOverlays);
            return () => {
                target.removeEventListener("keydown", onKeydown);
                target.removeEventListener("keyup", removeHotkeyOverlays);
                target.removeEventListener("blur", removeHotkeyOverlays);
                target.removeEventListener("click", removeHotkeyOverlays);
            };
        }

        /**
         * @param {KeyboardEvent} event
         */
        function onKeydown(event) {
            if (event.code?.startsWith("Numpad") && /^\d$/.test(event.key)) {
                return;
            }

            const hotkey = getActiveHotkey(event);
            if (!hotkey) {
                return;
            }
            const { activeElement, isBlocked } = ui;

            if (isBlocked) {
                return;
            }

            if (includesOverlayModifier(hotkey)) {
                adoptAccessKeys(activeElement);
            }

            if (!overlaysVisible && hotkey === hotkeyService.overlayModifier) {
                addHotkeyOverlays(activeElement);
                event.preventDefault();
                return;
            }

            const singleKey = hotkey.split("+").pop();
            if (!AUTHORIZED_KEYS.includes(singleKey)) {
                return;
            }

            const targetIsEditable =
                event.target instanceof HTMLElement &&
                (/input|textarea/i.test(event.target.tagName) ||
                    event.target.isContentEditable) &&
                !event.target.matches("input[type=checkbox], input[type=radio]");
            const shouldProtectEditable =
                targetIsEditable &&
                !(/** @type {HTMLElement} */ (event.target).dataset.allowHotkeys) &&
                singleKey !== "escape";

            const infos = {
                activeElement,
                hotkey,
                isRepeated: event.repeat,
                target: event.target,
                shouldProtectEditable,
            };
            const dispatched = dispatch(infos);
            if (dispatched) {
                event.preventDefault();
                event.stopImmediatePropagation();
            }

            if (overlaysVisible) {
                removeHotkeyOverlays();
                event.preventDefault();
            }
        }

        /**
         * @param {{
         *  activeElement: HTMLElement,
         *  hotkey: string,
         *  isRepeated: boolean,
         *  target: EventTarget,
         *  shouldProtectEditable: boolean,
         * }} infos
         * @returns {boolean}
         */
        function dispatch(infos) {
            const { activeElement, hotkey, isRepeated, target, shouldProtectEditable } =
                infos;

            const matchingRegistrations = registrationsByHotkey.get(hotkey);
            if (!matchingRegistrations?.size && !includesOverlayModifier(hotkey)) {
                return false;
            }

            const reversedRegistrations = matchingRegistrations
                ? Array.from(matchingRegistrations).reverse()
                : [];
            const domRegistrations = getDomRegistrations(hotkey, activeElement);
            const allRegistrations = [...reversedRegistrations, ...domRegistrations];

            const candidates = allRegistrations
                .map((reg) => ({ reg, area: reg.area?.() }))
                .filter(
                    ({ reg, area }) =>
                        (reg.allowRepeat || !isRepeated) &&
                        (reg.bypassEditableProtection || !shouldProtectEditable) &&
                        (reg.global || reg.activeElement === activeElement) &&
                        (!reg.isAvailable ||
                            reg.isAvailable(/** @type {HTMLElement} */ (target))) &&
                        (!reg.area ||
                            Boolean(
                                target &&
                                area &&
                                area.contains(/** @type {Node} */ (target)),
                            )),
                );

            let winner = candidates.shift();
            if (winner?.area) {
                for (const candidate of candidates) {
                    if (candidate.area && winner.area.contains(candidate.area)) {
                        winner = candidate;
                    }
                }
            }

            if (winner) {
                winner.reg.callback({
                    area: winner.area,
                    target,
                });
                return true;
            }
            return false;
        }

        /**
         * @param {string} hotkey
         * @param {HTMLElement} activeElement
         * @returns {HotkeyRegistration[]}
         */
        function getDomRegistrations(hotkey, activeElement) {
            if (!includesOverlayModifier(hotkey)) {
                return [];
            }

            const overlayModParts = hotkeyService.overlayModifier.split("+");
            const cleanHotkey = hotkey
                .split("+")
                .filter((key) => !overlayModParts.includes(key))
                .join("+");
            const elems = getVisibleElements(
                activeElement,
                `[data-hotkey='${cleanHotkey}' i]`,
            );
            return elems.map((el) => ({
                hotkey,
                activeElement,
                bypassEditableProtection: true,
                callback: () => {
                    if (document.activeElement) {
                        /** @type {HTMLElement} */ (document.activeElement).blur();
                    }
                    el.focus();
                    setTimeout(() => el.click());
                },
            }));
        }

        /**
         * @param {HTMLElement} activeElement
         */
        function addHotkeyOverlays(activeElement) {
            const hotkeysFromHookToHighlight = [];
            for (const [, registration] of registrations) {
                if (
                    !registration.global &&
                    registration.activeElement !== activeElement
                ) {
                    continue;
                }
                const overlayElement = registration.withOverlay?.();
                if (overlayElement) {
                    hotkeysFromHookToHighlight.push({
                        hotkey: registration.hotkey.replace(
                            `${hotkeyService.overlayModifier}+`,
                            "",
                        ),
                        el: overlayElement,
                    });
                }
            }

            const hotkeysFromDomToHighlight = getVisibleElements(
                activeElement,
                "[data-hotkey]:not(:disabled)",
            ).map((el) => ({ hotkey: el.dataset.hotkey, el }));

            const items = [...hotkeysFromDomToHighlight, ...hotkeysFromHookToHighlight];
            for (const item of items) {
                const hotkey = item.hotkey;
                const overlay = document.createElement("div");
                overlay.classList.add(
                    "o_web_hotkey_overlay",
                    "position-absolute",
                    "top-0",
                    "bottom-0",
                    "start-0",
                    "end-0",
                    "d-flex",
                    "justify-content-center",
                    "align-items-center",
                    "m-0",
                    "bg-black-50",
                    "h6",
                );
                overlay.style.zIndex = "1";
                const overlayKbd = document.createElement("kbd");
                overlayKbd.className = "small";
                overlayKbd.appendChild(document.createTextNode(hotkey.toUpperCase()));
                overlay.appendChild(overlayKbd);

                let overlayParent;
                if (item.el.tagName.toUpperCase() === "INPUT") {
                    overlayParent = item.el.parentElement;
                } else {
                    overlayParent = item.el;
                }

                if (getComputedStyle(overlayParent).position === "static") {
                    overlayParent.dataset.hotkeyOrigPosition =
                        overlayParent.style.position;
                    overlayParent.style.position = "relative";
                }
                overlayParent.appendChild(overlay);
            }
            overlaysVisible = true;
        }

        function removeHotkeyOverlays() {
            if (!overlaysVisible) {
                return;
            }
            for (const overlay of document.querySelectorAll(".o_web_hotkey_overlay")) {
                const parent = overlay.parentElement;
                overlay.remove();
                if (parent && "hotkeyOrigPosition" in parent.dataset) {
                    parent.style.position = parent.dataset.hotkeyOrigPosition;
                    delete parent.dataset.hotkeyOrigPosition;
                }
            }
            overlaysVisible = false;
        }

        /**
         * @param {string} hotkey
         * @param {HotkeyCallback} callback
         * @param {HotkeyOptions} [options]
         * @returns {number}
         */
        function registerHotkey(hotkey, callback, options = {}) {
            if (!hotkey || !hotkey.length) {
                throw new Error(
                    "You must specify an hotkey when registering a registration.",
                );
            }

            if (!callback || typeof callback !== "function") {
                throw new Error(
                    "You must specify a callback function when registering a registration.",
                );
            }

            const parts = hotkey
                .toLowerCase()
                .split("+")
                .map((part) => part.trim())
                .filter(Boolean);
            const modifiers = MODIFIERS.filter((modifier) => parts.includes(modifier));
            const keys = parts.filter((k) => !MODIFIERS.includes(k));
            if (keys.some((k) => !AUTHORIZED_KEYS.includes(k))) {
                throw new Error(
                    `You are trying to subscribe for an hotkey ('${hotkey}')
            that contains parts not whitelisted: ${keys.join(", ")}`,
                );
            } else if (keys.length > 1) {
                throw new Error(
                    `You are trying to subscribe for an hotkey ('${hotkey}')
            that contains more than one single key part: ${keys.join("+")}`,
                );
            }

            const token = nextToken++;
            /** @type {HotkeyRegistration} */
            const registration = {
                hotkey: [...modifiers, ...keys].join("+"),
                callback,
                activeElement: null,
                allowRepeat: options?.allowRepeat,
                bypassEditableProtection: options?.bypassEditableProtection,
                global: options?.global,
                area: options?.area,
                isAvailable: options?.isAvailable,
                withOverlay: options?.withOverlay,
            };

            queueMicrotask(() => {
                registration.activeElement = ui.activeElement;
            });

            registrations.set(token, registration);
            let sameHotkeyRegistrations = registrationsByHotkey.get(
                registration.hotkey,
            );
            if (!sameHotkeyRegistrations) {
                sameHotkeyRegistrations = new Set();
                registrationsByHotkey.set(registration.hotkey, sameHotkeyRegistrations);
            }
            sameHotkeyRegistrations.add(registration);
            return token;
        }

        /**
         * @param {number} token
         */
        function unregisterHotkey(token) {
            const registration = registrations.get(token);
            if (registration) {
                const sameHotkey = registrationsByHotkey.get(registration.hotkey);
                sameHotkey?.delete(registration);
                if (sameHotkey && !sameHotkey.size) {
                    registrationsByHotkey.delete(registration.hotkey);
                }
            }
            registrations.delete(token);
        }

        return {
            /**
             * @param {string} hotkey
             * @param {HotkeyCallback} callback
             * @param {HotkeyOptions} [options]
             * @returns {() => void}
             */
            add(hotkey, callback, options = {}) {
                const token = registerHotkey(hotkey, callback, options);
                return () => {
                    unregisterHotkey(token);
                };
            },
            /**
             * @param {HTMLIFrameElement} iframe
             * @returns {() => void}
             */
            registerIframe(iframe) {
                const iframeWindow = iframe?.contentWindow;
                if (!iframeWindow) {
                    return () => {};
                }
                const removeIframeListeners = addListeners(iframeWindow);
                const remove = () => {
                    listenerRemovers.delete(remove);
                    removeIframeListeners();
                };
                listenerRemovers.add(remove);
                return remove;
            },
            destroy() {
                for (const remove of [...listenerRemovers]) {
                    remove();
                }
                removeWindowListeners();
            },
        };
    },
};

registry.category("services").add("hotkey", /** @type {any} */ (hotkeyService));
/** @typedef {ReturnType<hotkeyService["start"]>} HotkeyService */
