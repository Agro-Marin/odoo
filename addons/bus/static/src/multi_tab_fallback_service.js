/** @odoo-module native */
import { EventBus } from "@odoo/owl";
import { browser } from "@web/core/browser/browser";
let multiTabId = 0;
/**
 * This service uses a Master/Slaves with Leader Election architecture in
 * order to keep track of the main tab. Tabs are synchronized thanks to the
 * localStorage.
 *
 * localStorage used keys are:
 * - multi_tab_service.lastPresenceByTab: mapping of tab ids to their last
 *   recorded presence.
 * - multi_tab_service.main: a boolean indicating whether a main tab is already
 *   present.
 * - multi_tab_service.heartbeat: last main tab heartbeat time.
 *
 * trigger:
 * - become_main_tab : when this tab became the main.
 * - no_longer_main_tab : when this tab is no longer the main.
 */
export const multiTabFallbackService = {
    start(env) {
        const bus = new EventBus();

        // CONSTANTS
        const TAB_HEARTBEAT_PERIOD = 10000; // 10 seconds
        const MAIN_TAB_HEARTBEAT_PERIOD = 1500; // 1.5 seconds
        const HEARTBEAT_OUT_OF_DATE_PERIOD = 5000; // 5 seconds
        const HEARTBEAT_KILL_OLD_PERIOD = 15000; // 15 seconds

        // PROPERTIES
        let _isOnMainTab = false;
        let lastHeartbeat = 0;
        let heartbeatTimeout;
        const now = new Date().getTime();
        // `this.name` is undefined on a service value (the registry key is not
        // copied onto it), so it contributed nothing but the string
        // "undefined". Two tabs opened in the same millisecond would then share
        // an identical tabId (per-tab `multiTabId` both start at 0) and clobber
        // each other's `lastPresenceByTab` entry, corrupting the election. A
        // random suffix makes the id collision-proof.
        const tabId = `${multiTabId++}:${now}:${Math.random().toString(36).slice(2)}`;

        function startElection() {
            if (_isOnMainTab) {
                return;
            }
            // Check who's next.
            const now = new Date().getTime();
            // ``JSON.parse(browser.localStorage.getItem(missingKey))`` returns
            // ``null`` on real localStorage but throws ``"undefined" is
            // not valid JSON`` when test patches return ``undefined``.
            // ``?? {}`` only catches null/undefined, not exceptions.
            // Coerce the raw value before parsing.
            const lastPresenceByTab = JSON.parse(
                browser.localStorage.getItem("multi_tab_service.lastPresenceByTab") ||
                    "{}",
            );
            const heartbeatKillOld = now - HEARTBEAT_KILL_OLD_PERIOD;
            let newMain;
            for (const [tab, lastPresence] of Object.entries(lastPresenceByTab)) {
                // Check for dead tabs.
                if (lastPresence < heartbeatKillOld) {
                    continue;
                }
                newMain = tab;
                break;
            }
            if (newMain === tabId) {
                // We're next in queue. Electing as main.
                lastHeartbeat = now;
                browser.localStorage.setItem(
                    "multi_tab_service.heartbeat",
                    lastHeartbeat,
                );
                browser.localStorage.setItem("multi_tab_service.main", true);
                _isOnMainTab = true;
                bus.trigger("become_main_tab");
                // Removing main peer from queue.
                delete lastPresenceByTab[newMain];
                browser.localStorage.setItem(
                    "multi_tab_service.lastPresenceByTab",
                    JSON.stringify(lastPresenceByTab),
                );
            }
        }

        function heartbeat() {
            const now = new Date().getTime();
            let heartbeatValue = parseInt(
                browser.localStorage.getItem("multi_tab_service.heartbeat") ?? 0,
            );
            // ``JSON.parse(browser.localStorage.getItem(missingKey))`` returns
            // ``null`` on real localStorage but throws ``"undefined" is
            // not valid JSON`` when test patches return ``undefined``.
            // ``?? {}`` only catches null/undefined, not exceptions.
            // Coerce the raw value before parsing.
            const lastPresenceByTab = JSON.parse(
                browser.localStorage.getItem("multi_tab_service.lastPresenceByTab") ||
                    "{}",
            );
            if (heartbeatValue + HEARTBEAT_OUT_OF_DATE_PERIOD < now) {
                // Heartbeat is out of date. Electing new main.
                startElection();
                heartbeatValue = parseInt(
                    browser.localStorage.getItem("multi_tab_service.heartbeat") ?? 0,
                );
            }
            if (_isOnMainTab) {
                // Walk through all tabs and kill old ones.
                const cleanedTabs = {};
                for (const [tabId, lastPresence] of Object.entries(lastPresenceByTab)) {
                    if (lastPresence + HEARTBEAT_KILL_OLD_PERIOD > now) {
                        cleanedTabs[tabId] = lastPresence;
                    }
                }
                if (heartbeatValue !== lastHeartbeat) {
                    // Someone else is also main...
                    // It should not happen, except in some race condition situation.
                    _isOnMainTab = false;
                    lastHeartbeat = 0;
                    lastPresenceByTab[tabId] = now;
                    browser.localStorage.setItem(
                        "multi_tab_service.lastPresenceByTab",
                        JSON.stringify(lastPresenceByTab),
                    );
                    bus.trigger("no_longer_main_tab");
                } else {
                    lastHeartbeat = now;
                    browser.localStorage.setItem("multi_tab_service.heartbeat", now);
                    browser.localStorage.setItem(
                        "multi_tab_service.lastPresenceByTab",
                        JSON.stringify(cleanedTabs),
                    );
                }
            } else {
                // Update own heartbeat.
                lastPresenceByTab[tabId] = now;
                browser.localStorage.setItem(
                    "multi_tab_service.lastPresenceByTab",
                    JSON.stringify(lastPresenceByTab),
                );
            }
            const hbPeriod = _isOnMainTab
                ? MAIN_TAB_HEARTBEAT_PERIOD
                : TAB_HEARTBEAT_PERIOD;
            heartbeatTimeout = browser.setTimeout(heartbeat, hbPeriod);
        }

        function onStorage({ key, newValue }) {
            if (key === "multi_tab_service.main" && !newValue) {
                // Main was unloaded.
                startElection();
            }
        }

        /**
         * Unregister this tab from the multi-tab service. It will no longer
         * be able to become the main tab.
         */
        function unregister() {
            clearTimeout(heartbeatTimeout);
            // ``JSON.parse(browser.localStorage.getItem(missingKey))`` returns
            // ``null`` on real localStorage but throws ``"undefined" is
            // not valid JSON`` when test patches return ``undefined``.
            // ``?? {}`` only catches null/undefined, not exceptions.
            // Coerce the raw value before parsing.
            const lastPresenceByTab = JSON.parse(
                browser.localStorage.getItem("multi_tab_service.lastPresenceByTab") ||
                    "{}",
            );
            delete lastPresenceByTab[tabId];
            browser.localStorage.setItem(
                "multi_tab_service.lastPresenceByTab",
                JSON.stringify(lastPresenceByTab),
            );

            // Unload main.
            if (_isOnMainTab) {
                _isOnMainTab = false;
                bus.trigger("no_longer_main_tab");
                browser.localStorage.removeItem("multi_tab_service.main");
            }
        }

        browser.addEventListener("pagehide", unregister);
        browser.addEventListener("pageshow", (ev) => {
            if (!ev.persisted) {
                return;
            }
            // Restored from bfcache: `pagehide` unregistered this tab (cleared
            // its heartbeat and removed it from `lastPresenceByTab`). Without
            // re-registering, the tab can never become main again. Re-add its
            // presence and resume the heartbeat loop (unregister cleared the
            // pending timeout, so this doesn't double-schedule).
            const lastPresenceByTab = JSON.parse(
                browser.localStorage.getItem("multi_tab_service.lastPresenceByTab") ||
                    "{}",
            );
            lastPresenceByTab[tabId] = new Date().getTime();
            browser.localStorage.setItem(
                "multi_tab_service.lastPresenceByTab",
                JSON.stringify(lastPresenceByTab),
            );
            heartbeat();
        });
        browser.addEventListener("storage", onStorage);

        // REGISTER THIS TAB
        // ``getItem`` returns ``null`` in real localStorage which
        // ``JSON.parse`` accepts (-> null), but test patches sometimes
        // return ``undefined`` for missing keys. ``JSON.parse(undefined)``
        // throws ``"undefined" is not valid JSON``; ``??`` doesn't catch
        // exceptions. Coerce to a known-safe fallback string before
        // parsing.
        const lastPresenceByTab = JSON.parse(
            browser.localStorage.getItem("multi_tab_service.lastPresenceByTab") || "{}",
        );
        lastPresenceByTab[tabId] = now;
        browser.localStorage.setItem(
            "multi_tab_service.lastPresenceByTab",
            JSON.stringify(lastPresenceByTab),
        );

        if (!browser.localStorage.getItem("multi_tab_service.main")) {
            startElection();
        }
        heartbeat();

        return {
            bus,
            /**
             * Determine whether or not this tab is the main one.
             * it's intentionally an async function to match the API of
             * multiTabSharedWorkerService
             *
             * @returns {boolean}
             */
            async isOnMainTab() {
                return _isOnMainTab;
            },
            /**
             * Unregister this tab from the multi-tab service. It will no longer
             * be able to become the main tab.
             */
            unregister,
        };
    },
};
