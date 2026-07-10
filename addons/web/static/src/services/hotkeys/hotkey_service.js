// @ts-check
/** @odoo-module native */

/** @module @web/services/hotkeys/hotkey_service - Keyboard shortcut registration, dispatch, and overlay access-key management */

import { browser } from "@web/core/browser/browser";
import { AUTHORIZED_KEYS, getActiveHotkey, MODIFIERS } from "@web/core/browser/hotkeys";
import { registry } from "@web/core/registry";
import { getVisibleElements } from "@web/core/utils/dom/ui";

// Re-export for backward compatibility — consumers should migrate to @web/core/browser/hotkeys
export { getActiveHotkey };

/**
 * @typedef {(context: { area: HTMLElement, target: EventTarget }) => void} HotkeyCallback
 *
 * @typedef {Object} HotkeyOptions
 * @property {boolean} [allowRepeat]
 *  allow registration to perform multiple times when hotkey is held down
 * @property {boolean} [bypassEditableProtection]
 *  if true the hotkey service will call this registration
 *  even if an editable element is focused
 * @property {boolean} [global]
 *  allow registration to perform no matter the UI active element
 * @property {() => HTMLElement} [area]
 *  adds a restricted operating area for this hotkey
 * @property {(target: HTMLElement) => boolean} [isAvailable]
 *  adds a validation before calling the hotkey registration's callback
 * @property {() => HTMLElement} [withOverlay]
 *  provides the element on which the overlay should be displayed;
 *  if provided, the hotkey only fires via the overlay access key,
 *  like all [data-hotkey] DOM attributes.
 *
 * @typedef {HotkeyOptions & {
 *  hotkey: string,
 *  callback: HotkeyCallback,
 *  activeElement: HTMLElement | null,
 * }} HotkeyRegistration
 */

export const hotkeyService = {
    dependencies: ["ui"],
    // All odoo hotkeys assume this modifier; changing it may conflict with existing shortcuts.
    overlayModifier: "alt",
    /**
     * @param {import("@web/env").OdooEnv} env
     * @param {{ ui: any }} services
     */
    start(env, { ui }) {
        /** @type {Map<number, HotkeyRegistration>} */
        const registrations = new Map();
        /**
         * Secondary index for dispatch: registrations grouped by hotkey, in
         * insertion order (Sets preserve it), so a keydown only inspects the
         * registrations that can actually match instead of all of them.
         * @type {Map<string, Set<HotkeyRegistration>>}
         */
        const registrationsByHotkey = new Map();
        let nextToken = 0;
        let overlaysVisible = false;

        /**
         * Whether the hotkey contains every part of the overlay modifier —
         * the precondition for the [accesskey] takeover and DOM [data-hotkey] registrations.
         * @param {string} hotkey
         * @returns {boolean}
         */
        function includesOverlayModifier(hotkey) {
            return hotkeyService.overlayModifier
                .split("+")
                .every((part) => hotkey.includes(part));
        }

        addListeners(/** @type {any} */ (browser));

        /**
         * @param {Window} target
         * @returns {() => void} disposer that detaches every listener it added
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
         * Dispatch guard: bails out if UI is blocked or the key isn't whitelisted.
         * @param {KeyboardEvent} event
         */
        function onKeydown(event) {
            if (event.code?.startsWith("Numpad") && /^\d$/.test(event.key)) {
                // Ignore Keypad number keys — Windows ALT+[numeric code] inputs ASCII/Unicode
                // chars this way. See https://support.microsoft.com/en-us/office/insert-ascii-or-unicode-latin-based-symbols-and-characters-d13f58d3-7bcb-44a7-a4d5-972ee12e50e0#bm1
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

            // Replace [accesskey] attrs with [data-hotkey] to take over the default accesskey
            // behavior and avoid conflicts. Only overlay-modifier presses reach these elements,
            // so skip the full-document scan otherwise.
            if (includesOverlayModifier(hotkey)) {
                const elementsWithAccessKey = document.querySelectorAll("[accesskey]");
                for (const el of elementsWithAccessKey) {
                    if (el instanceof HTMLElement) {
                        el.dataset.hotkey = el.accessKey;
                        el.removeAttribute("accesskey");
                    }
                }
            }

            // Special case: open hotkey overlays
            if (!overlaysVisible && hotkey === hotkeyService.overlayModifier) {
                addHotkeyOverlays(activeElement);
                event.preventDefault();
                return;
            }

            const singleKey = hotkey.split("+").pop();
            if (!AUTHORIZED_KEYS.includes(singleKey)) {
                return;
            }

            // Protect any editable target that does not explicitly accept hotkeys
            // NB: except for ESC, which is always allowed as hotkey in editables.
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
                // Prevent browser defaults
                event.preventDefault();
                // Stop other window keydown listeners (e.g. home menu)
                event.stopImmediatePropagation();
            }

            if (overlaysVisible) {
                removeHotkeyOverlays();
                event.preventDefault();
            }
        }

        /**
         * Dispatches an hotkey to first matching registration.
         * Registrations are iterated in following order:
         * - priority to all registrations done through the hotkeyService.add()
         *   method (NB: in descending order of insertion = newer first)
         * - then all registrations done through the DOM [data-hotkey] attribute
         *
         * @param {{
         *  activeElement: HTMLElement,
         *  hotkey: string,
         *  isRepeated: boolean,
         *  target: EventTarget,
         *  shouldProtectEditable: boolean,
         * }} infos
         * @returns {boolean} true if has been dispatched
         */
        function dispatch(infos) {
            const { activeElement, hotkey, isRepeated, target, shouldProtectEditable } =
                infos;

            // Only registrations under this exact hotkey can match; DOM [data-hotkey]
            // registrations also need the overlay modifier — bail out early otherwise.
            const matchingRegistrations = registrationsByHotkey.get(hotkey);
            if (!matchingRegistrations?.size && !includesOverlayModifier(hotkey)) {
                return false;
            }

            const reversedRegistrations = matchingRegistrations
                ? Array.from(matchingRegistrations).reverse()
                : [];
            const domRegistrations = getDomRegistrations(hotkey, activeElement);
            const allRegistrations = [...reversedRegistrations, ...domRegistrations];

            const candidates = allRegistrations.filter(
                (reg) =>
                    (reg.allowRepeat || !isRepeated) &&
                    (reg.bypassEditableProtection || !shouldProtectEditable) &&
                    (reg.global || reg.activeElement === activeElement) &&
                    (!reg.isAvailable ||
                        reg.isAvailable(/** @type {HTMLElement} */ (target))) &&
                    (!reg.area ||
                        (target &&
                            reg.area() &&
                            reg.area().contains(/** @type {Node} */ (target)))),
            );

            let winner = candidates.shift();
            if (winner?.area) {
                // If there is an area, find the closest one
                for (const candidate of candidates.filter((c) => Boolean(c.area))) {
                    if (candidate.area() && winner.area().contains(candidate.area())) {
                        winner = candidate;
                    }
                }
            }

            if (winner) {
                winner.callback({
                    area: winner.area?.(),
                    target,
                });
                return true;
            }
            return false;
        }

        /**
         * Get a list of registrations from the [data-hotkey] defined in the DOM
         *
         * @param {string} hotkey
         * @param {HTMLElement} activeElement
         * @returns {HotkeyRegistration[]}
         */
        function getDomRegistrations(hotkey, activeElement) {
            if (!includesOverlayModifier(hotkey)) {
                return [];
            }

            // Get all elements having a data-hotkey attribute  and matching
            // the actual hotkey without the overlayModifier.
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
         * Add the hotkey overlays respecting the ui active element.
         * @param {HTMLElement} activeElement
         */
        function addHotkeyOverlays(activeElement) {
            // Gather the hotkeys to overlay registered through the useHotkey hook.
            const hotkeysFromHookToHighlight = [];
            for (const [, registration] of registrations) {
                // Only highlight hotkeys ``dispatch`` would actually route to this active
                // element (same filter): a hotkey behind a now-open dialog won't dispatch,
                // so showing its badge would be misleading.
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

            // Gather the hotkeys to overlay registered through the DOM datasets.
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
                    // special case for the search input that has an access key
                    // defined. We cannot set the overlay on the input itself,
                    // only on its parent.
                    overlayParent = item.el.parentElement;
                } else {
                    overlayParent = item.el;
                }

                if (overlayParent.style.position !== "absolute") {
                    overlayParent.dataset.hotkeyOrigPosition =
                        overlayParent.style.position;
                    overlayParent.style.position = "relative";
                }
                overlayParent.appendChild(overlay);
            }
            overlaysVisible = true;
        }

        function removeHotkeyOverlays() {
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
         * Registers a new hotkey.
         *
         * @param {string} hotkey
         * @param {HotkeyCallback} callback
         * @param {HotkeyOptions} [options]
         * @returns {number} registration token
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

            /**
             * An hotkey must comply to these rules:
             *  - all parts are whitelisted
             *  - single key part comes last
             *  - each part is separated by the dash character: "+"
             */
            const keys = hotkey
                .toLowerCase()
                .split("+")
                .filter((k) => !MODIFIERS.includes(k));
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
                hotkey: hotkey.toLowerCase(),
                callback,
                activeElement: null,
                allowRepeat: options?.allowRepeat,
                bypassEditableProtection: options?.bypassEditableProtection,
                global: options?.global,
                area: options?.area,
                isAvailable: options?.isAvailable,
                withOverlay: options?.withOverlay,
            };

            // Due to the way elements are mounted in the DOM by Owl (bottom-to-top),
            // we need to wait the next micro task tick to set the context owner of the registration.
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
                registrationsByHotkey.get(registration.hotkey)?.delete(registration);
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
             * Attach the hotkey listeners to an iframe's window.
             * @param {HTMLIFrameElement} iframe
             * @returns {() => void} disposer — call it on iframe removal/unmount
             *   to avoid leaking the four listeners (and retaining the detached
             *   window) every time the iframe is re-created.
             */
            registerIframe(iframe) {
                return addListeners(iframe.contentWindow);
            },
        };
    },
};

registry.category("services").add("hotkey", /** @type {any} */ (hotkeyService));
/** @typedef {ReturnType<hotkeyService["start"]>} HotkeyService */
