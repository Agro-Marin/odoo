/** @odoo-module native */
import { luxon } from "@web/core/l10n/luxon";
import { EventBus } from "@odoo/owl";
import { browser } from "@web/core/browser/browser";
import { registry } from "@web/core/registry";
import { timings } from "../misc.js";

// Throttle window for input-driven presence updates: a click/keydown storm
// otherwise triggers one synchronous localStorage write (and a cross-tab
// `storage` event) per event. Presence is minute-grained, so ~1s is invisible.
const PRESENCE_THROTTLE_MS = 1000;
export const presenceService = {
    start(env) {
        const LOCAL_STORAGE_PREFIX = "presence";
        const bus = new EventBus();
        let isOdooFocused = true;
        let lastPresenceTime =
            browser.localStorage.getItem(`${LOCAL_STORAGE_PREFIX}.lastPresence`) ||
            luxon.DateTime.now().ts;

        function onPresence() {
            lastPresenceTime = luxon.DateTime.now().ts;
            browser.localStorage.setItem(
                `${LOCAL_STORAGE_PREFIX}.lastPresence`,
                lastPresenceTime,
            );
            bus.trigger("presence");
        }

        function onFocusChange(isFocused) {
            // In an embedded context (iframe, e.g. livechat), this window's own
            // focus/blur events are unreliable, so defer to the parent
            // document's focus state. In a top-level page, trust the intent
            // carried by the event (a genuine blur/pagehide must not be flipped
            // back to "focused" by a momentarily-stale `hasFocus()`).
            try {
                if (parent !== self) {
                    isFocused = parent.document.hasFocus();
                }
            } catch {
                // Cross-origin parent: keep the event-supplied value.
            }
            isOdooFocused = isFocused;
            browser.localStorage.setItem(
                `${LOCAL_STORAGE_PREFIX}.focus`,
                isOdooFocused,
            );
            if (isOdooFocused) {
                lastPresenceTime = luxon.DateTime.now().ts;
                env.bus.trigger("window_focus", isOdooFocused);
            }
        }

        function onStorage({ key, newValue }) {
            if (key === `${LOCAL_STORAGE_PREFIX}.focus`) {
                isOdooFocused = JSON.parse(newValue);
                env.bus.trigger("window_focus", isOdooFocused);
            }
            if (key === `${LOCAL_STORAGE_PREFIX}.lastPresence`) {
                lastPresenceTime = JSON.parse(newValue);
                bus.trigger("presence");
            }
        }
        const throttledOnPresence = timings.throttle(onPresence, PRESENCE_THROTTLE_MS);
        browser.addEventListener("storage", onStorage);
        browser.addEventListener("focus", () => onFocusChange(true));
        browser.addEventListener("blur", () => onFocusChange(false));
        browser.addEventListener("pagehide", () => onFocusChange(false));
        browser.addEventListener("click", throttledOnPresence, true);
        browser.addEventListener("keydown", throttledOnPresence, true);

        return {
            bus,
            getLastPresence() {
                return lastPresenceTime;
            },
            isOdooFocused() {
                return isOdooFocused;
            },
            getInactivityPeriod() {
                return luxon.DateTime.now().ts - this.getLastPresence();
            },
        };
    },
};

registry.category("services").add("presence", presenceService);
