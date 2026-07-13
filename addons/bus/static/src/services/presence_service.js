/** @odoo-module native */
import { EventBus } from "@odoo/owl";
import { browser } from "@web/core/browser/browser";
import { luxon } from "@web/core/l10n/luxon";
import { registry } from "@web/core/registry";

import { throttle } from "../misc.js";

// Throttle window for input-driven presence updates: a click/keydown storm
// otherwise triggers one synchronous localStorage write (and a cross-tab
// `storage` event) per event. Presence is minute-grained, so ~1s is invisible.
const PRESENCE_THROTTLE_MS = 1000;
export const presenceService = {
    start(env) {
        const LOCAL_STORAGE_PREFIX = "presence";
        const bus = new EventBus();
        // Initialize from the real focus state, not an optimistic `true`: a tab
        // opened in the background (middle-click, target=_blank) never receives
        // a `blur` (it never had focus), so a hardcoded `true` would report it
        // focused until the first real focus transition — suppressing mail's
        // out-of-focus counters/sounds on exactly the tab type they exist for.
        let isOdooFocused = document.hasFocus();
        // Stored as a number by onPresence/onStorage; localStorage returns it
        // as a string (or null when absent). Parse so getLastPresence() always
        // yields a number, not a string on first load.
        let lastPresenceTime =
            parseInt(
                browser.localStorage.getItem(`${LOCAL_STORAGE_PREFIX}.lastPresence`),
            ) || luxon.DateTime.now().ts;

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
                if (parent !== window) {
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
            }
            // Fire on BOTH transitions: cross-tab consumers get the `false`
            // through the storage event, but same-tab listeners (e.g. mail's
            // out-of-focus counter) would otherwise only ever hear about
            // gained focus, never about losing it.
            env.bus.trigger("window_focus", isOdooFocused);
        }

        function onStorage({ key, newValue }) {
            // `newValue` is null when the key is removed (e.g. a "clear site
            // data" in another tab): parsing it would poison the local state
            // — a nullish `lastPresenceTime` makes `getInactivityPeriod()`
            // return an epoch-scale number, flagging the user as inactive for
            // 50+ years. Keep the current local values instead.
            if (newValue == null) {
                return;
            }
            if (key === `${LOCAL_STORAGE_PREFIX}.focus`) {
                isOdooFocused = JSON.parse(newValue);
                env.bus.trigger("window_focus", isOdooFocused);
            }
            if (key === `${LOCAL_STORAGE_PREFIX}.lastPresence`) {
                lastPresenceTime = JSON.parse(newValue);
                bus.trigger("presence");
            }
        }
        const throttledOnPresence = throttle(onPresence, PRESENCE_THROTTLE_MS);
        browser.addEventListener("storage", onStorage);
        browser.addEventListener("focus", () => onFocusChange(true));
        browser.addEventListener("blur", () => onFocusChange(false));
        browser.addEventListener("pagehide", () => onFocusChange(false));
        browser.addEventListener("pageshow", (ev) => {
            if (ev.persisted) {
                // Restored from bfcache: `pagehide` force-unfocused this tab;
                // restore the real focus state (the browser does not replay a
                // `focus` event for an already-focused restored page).
                onFocusChange(document.hasFocus());
            }
        });
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
