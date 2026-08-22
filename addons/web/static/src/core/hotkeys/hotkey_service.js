// @ts-check
/** @odoo-module native */

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
 * @property {() => Document | HTMLElement | null} [scope]
 * @typedef {HotkeyOptions & {
 * hotkey: string,
 * callback: HotkeyCallback,
 * getScope: () => Document | HTMLElement,
 * }} HotkeyRegistration
 */

export class HotkeyService {
    /**
     * @param {{ ui: any }} services
     */
    constructor({ ui }) {
        this.ui = ui;
        /** @type {Map<number, HotkeyRegistration>} */
        this.registrations = new Map();
        /** @type {Map<string, Set<HotkeyRegistration>>} */
        this.registrationsByHotkey = new Map();
        this.nextToken = 0;
        this.overlaysVisible = false;
        /** @type {Set<() => void>} */
        this.listenerRemovers = new Set();
        this.removeWindowListeners = this.addListeners(/** @type {any} */ (browser));
    }

    /**
     * @returns {string}
     */
    get overlayModifier() {
        return hotkeyService.overlayModifier;
    }

    /**
     * @param {string} hotkey
     * @returns {boolean}
     */
    includesOverlayModifier(hotkey) {
        const tokens = hotkey.split("+");
        return this.overlayModifier.split("+").every((mod) => tokens.includes(mod));
    }

    /**
     * @param {Window} target
     * @returns {() => void}
     */
    addListeners(target) {
        const onKeydown = (/** @type {any} */ ev) => this.onKeydown(ev);
        const removeOverlays = () => this.removeHotkeyOverlays();
        target.addEventListener("keydown", onKeydown);
        target.addEventListener("keyup", removeOverlays);
        target.addEventListener("blur", removeOverlays);
        target.addEventListener("click", removeOverlays);
        return () => {
            target.removeEventListener("keydown", onKeydown);
            target.removeEventListener("keyup", removeOverlays);
            target.removeEventListener("blur", removeOverlays);
            target.removeEventListener("click", removeOverlays);
        };
    }

    /**
     * @param {KeyboardEvent} event
     */
    onKeydown(event) {
        if (event.code?.startsWith("Numpad") && /^\d$/.test(event.key)) {
            return;
        }

        const hotkey = getActiveHotkey(event);
        if (!hotkey) {
            return;
        }
        const { activeElement, isBlocked } = this.ui;

        if (isBlocked) {
            return;
        }

        if (this.includesOverlayModifier(hotkey)) {
            adoptAccessKeys(activeElement);
        }

        if (!this.overlaysVisible && hotkey === this.overlayModifier) {
            this.addHotkeyOverlays(activeElement);
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
        const dispatched = this.dispatch(infos);
        if (dispatched) {
            event.preventDefault();
            event.stopImmediatePropagation();
        }

        if (this.overlaysVisible) {
            this.removeHotkeyOverlays();
            event.preventDefault();
        }
    }

    /**
     * @param {{
     * activeElement: HTMLElement,
     * hotkey: string,
     * isRepeated: boolean,
     * target: EventTarget,
     * shouldProtectEditable: boolean,
     * }} infos
     * @returns {boolean}
     */
    dispatch(infos) {
        const { activeElement, hotkey, isRepeated, target, shouldProtectEditable } =
            infos;

        const matchingRegistrations = this.registrationsByHotkey.get(hotkey);
        if (!matchingRegistrations?.size && !this.includesOverlayModifier(hotkey)) {
            return false;
        }

        const reversedRegistrations = matchingRegistrations
            ? Array.from(matchingRegistrations).reverse()
            : [];
        const domRegistrations = this.getDomRegistrations(hotkey, activeElement);
        const allRegistrations = [...reversedRegistrations, ...domRegistrations];

        const candidates = allRegistrations
            .map((reg) => ({ reg, area: reg.area?.() }))
            .filter(
                ({ reg, area }) =>
                    (reg.allowRepeat || !isRepeated) &&
                    (reg.bypassEditableProtection || !shouldProtectEditable) &&
                    (reg.global || reg.getScope() === activeElement) &&
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
    getDomRegistrations(hotkey, activeElement) {
        if (!this.includesOverlayModifier(hotkey)) {
            return [];
        }

        const overlayModParts = this.overlayModifier.split("+");
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
            getScope: () => activeElement,
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
    addHotkeyOverlays(activeElement) {
        const hotkeysFromHookToHighlight = [];
        for (const [, registration] of this.registrations) {
            if (!registration.global && registration.getScope() !== activeElement) {
                continue;
            }
            const overlayElement = registration.withOverlay?.();
            if (overlayElement) {
                hotkeysFromHookToHighlight.push({
                    hotkey: registration.hotkey.replace(`${this.overlayModifier}+`, ""),
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
                overlayParent.dataset.hotkeyOrigPosition = overlayParent.style.position;
                overlayParent.style.position = "relative";
            }
            overlayParent.appendChild(overlay);
        }
        this.overlaysVisible = true;
    }

    removeHotkeyOverlays() {
        if (!this.overlaysVisible) {
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
        this.overlaysVisible = false;
    }

    /**
     * @param {string} hotkey
     * @param {HotkeyCallback} callback
     * @param {HotkeyOptions} [options]
     * @returns {number}
     */
    registerHotkey(hotkey, callback, options = {}) {
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

        const token = this.nextToken++;
        const capturedScope = this.ui.activeElement;
        /** @type {HotkeyRegistration} */
        const registration = {
            hotkey: [...modifiers, ...keys].join("+"),
            callback,
            getScope: options?.scope ?? (() => capturedScope),
            allowRepeat: options?.allowRepeat,
            bypassEditableProtection: options?.bypassEditableProtection,
            global: options?.global,
            area: options?.area,
            isAvailable: options?.isAvailable,
            withOverlay: options?.withOverlay,
        };

        this.registrations.set(token, registration);
        let sameHotkeyRegistrations = this.registrationsByHotkey.get(
            registration.hotkey,
        );
        if (!sameHotkeyRegistrations) {
            sameHotkeyRegistrations = new Set();
            this.registrationsByHotkey.set(
                registration.hotkey,
                sameHotkeyRegistrations,
            );
        }
        sameHotkeyRegistrations.add(registration);
        return token;
    }

    /**
     * @param {number} token
     */
    unregisterHotkey(token) {
        const registration = this.registrations.get(token);
        if (registration) {
            const sameHotkey = this.registrationsByHotkey.get(registration.hotkey);
            sameHotkey?.delete(registration);
            if (sameHotkey && !sameHotkey.size) {
                this.registrationsByHotkey.delete(registration.hotkey);
            }
        }
        this.registrations.delete(token);
    }

    /**
     * @param {string} hotkey
     * @param {HotkeyCallback} callback
     * @param {HotkeyOptions} [options]
     * @returns {() => void}
     */
    add(hotkey, callback, options = {}) {
        const token = this.registerHotkey(hotkey, callback, options);
        return () => {
            this.unregisterHotkey(token);
        };
    }

    /**
     * @param {HTMLIFrameElement} iframe
     * @returns {() => void}
     */
    registerIframe(iframe) {
        const iframeWindow = iframe?.contentWindow;
        if (!iframeWindow) {
            return () => {};
        }
        const removeIframeListeners = this.addListeners(iframeWindow);
        const remove = () => {
            this.listenerRemovers.delete(remove);
            removeIframeListeners();
        };
        this.listenerRemovers.add(remove);
        return remove;
    }

    destroy() {
        for (const remove of [...this.listenerRemovers]) {
            remove();
        }
        this.removeWindowListeners();
    }
}

export const hotkeyService = {
    dependencies: ["ui"],
    overlayModifier: "alt",
    /**
     * @param {import("@web/env").OdooEnv} env
     * @param {{ ui: any }} services
     * @returns {HotkeyService}
     */
    start(env, { ui }) {
        return new HotkeyService({ ui });
    },
};

registry.category("services").add("hotkey", /** @type {any} */ (hotkeyService));
