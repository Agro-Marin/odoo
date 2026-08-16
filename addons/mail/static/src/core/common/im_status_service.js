/** @odoo-module native */
import { browser } from "@web/core/browser/browser";
import { registry } from "@web/core/registry";
export const AWAY_DELAY = 30 * 60 * 1000;

export const imStatusService = {
    dependencies: ["bus_service", "presence"],

    /**
     * @param {import("@web/env").OdooEnv} env
     * @param {{ bus_service: any, presence: any }} services
     */
    start(env, { bus_service, presence }) {
        let lastSentInactivity;
        let becomeAwayTimeout;

        const updateBusPresence = () => {
            lastSentInactivity = presence.getInactivityPeriod();
            startAwayTimeout();
            bus_service.send("update_presence", {
                inactivity_period: lastSentInactivity,
            });
        };

        const startAwayTimeout = () => {
            clearTimeout(becomeAwayTimeout);
            const awayTime = AWAY_DELAY - presence.getInactivityPeriod();
            if (awayTime > 0) {
                becomeAwayTimeout = browser.setTimeout(
                    () => updateBusPresence(),
                    awayTime,
                );
            }
        };
        bus_service.addEventListener("BUS:CONNECT", () => updateBusPresence());
        bus_service.addEventListener("BUS:RECONNECT", () => updateBusPresence());
        bus_service.subscribe(
            "bus.bus/im_status_updated",
            /**
             * @param {Object} payload
             * @param {string} payload.presence_status
             * @param {string} payload.im_status
             * @param {number} [payload.partner_id]
             * @param {number} [payload.guest_id]
             * @param {boolean} [payload.debounce=true]
             */
            async ({
                presence_status,
                im_status,
                partner_id,
                guest_id,
                debounce = true,
            }) => {
                const store = env.services["mail.store"];
                const partner = store["res.partner"].get(partner_id);
                const guest = store["mail.guest"].get(guest_id);
                if (!partner && !guest) {
                    return;
                }
                if (debounce) {
                    partner?.debouncedSetImStatus(im_status);
                    guest?.debouncedSetImStatus(im_status);
                } else {
                    partner?.updateImStatus(im_status);
                    guest?.updateImStatus(im_status);
                }
                if (partner?.eq(store.self_partner) || guest?.eq(store.self_guest)) {
                    const isOnline = presence.getInactivityPeriod() < AWAY_DELAY;
                    if (
                        (presence_status === "away" && isOnline) ||
                        presence_status === "offline"
                    ) {
                        updateBusPresence();
                    }
                }
            },
        );
        presence.bus.addEventListener("presence", () => {
            if (lastSentInactivity === undefined || lastSentInactivity >= AWAY_DELAY) {
                updateBusPresence();
            }
            startAwayTimeout();
        });
        return { updateBusPresence };
    },
};

registry.category("services").add("im_status", imStatusService);
