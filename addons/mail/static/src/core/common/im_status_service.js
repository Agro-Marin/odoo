// @ts-check
/** @odoo-module native */
import { browser } from "@web/core/browser/browser";
import { makeLogger } from "@web/core/debug/debug_logger";
import { registry } from "@web/core/registry";
export const AWAY_DELAY = 30 * 60 * 1000;

const log = makeLogger("mail.im_status");

export class ImStatusService {
    /**
     * @param {import("@web/env").OdooEnv} env
     * @param {{ bus_service: any, presence: any }} services
     */
    constructor(env, { bus_service, presence }) {
        this.env = env;
        this.busService = bus_service;
        this.presence = presence;
        this.lastSentInactivity = undefined;
        this.becomeAwayTimeout = undefined;
    }

    setup() {
        this.busService.addEventListener("BUS:CONNECT", () => this.updateBusPresence());
        this.busService.addEventListener("BUS:RECONNECT", () =>
            this.updateBusPresence(),
        );
        this.busService.subscribe("bus.bus/im_status_updated", (payload) => {
            log.pipeline("bus.bus/im_status_updated", () => payload);
            this.onImStatusUpdated(payload);
        });
        this.presence.bus.addEventListener("presence", () => {
            if (
                this.lastSentInactivity === undefined ||
                this.lastSentInactivity >= AWAY_DELAY
            ) {
                this.updateBusPresence();
            }
            this.startAwayTimeout();
        });
    }

    updateBusPresence() {
        this.lastSentInactivity = this.presence.getInactivityPeriod();
        log.logic("updateBusPresence", () => ({ inactivity: this.lastSentInactivity }));
        this.startAwayTimeout();
        this.busService.send("update_presence", {
            inactivity_period: this.lastSentInactivity,
        });
    }

    startAwayTimeout() {
        clearTimeout(this.becomeAwayTimeout);
        const awayTime = AWAY_DELAY - this.presence.getInactivityPeriod();
        log.logic("startAwayTimeout", () => ({ awayTime }));
        if (awayTime > 0) {
            this.becomeAwayTimeout = browser.setTimeout(
                () => this.updateBusPresence(),
                awayTime,
            );
        }
    }

    /**
     * @param {Object} payload
     * @param {string} payload.presence_status
     * @param {import("./mail_guest_model").ImStatus} payload.im_status
     * @param {number} [payload.partner_id]
     * @param {number} [payload.guest_id]
     * @param {boolean} [payload.debounce=true]
     */
    async onImStatusUpdated({
        presence_status,
        im_status,
        partner_id,
        guest_id,
        debounce = true,
    }) {
        const store = this.env.services["mail.store"];
        const partner = store["res.partner"].get(partner_id);
        const guest = store["mail.guest"].get(guest_id);
        if (!partner && !guest) {
            log.logic("onImStatusUpdated for unknown persona", () => ({
                partner_id,
                guest_id,
            }));
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
            const isOnline = this.presence.getInactivityPeriod() < AWAY_DELAY;
            if (
                (presence_status === "away" && isOnline) ||
                presence_status === "offline"
            ) {
                log.logic("self presence disagrees with server", () => ({
                    presence_status,
                    isOnline,
                }));
                this.updateBusPresence();
            }
        }
    }
}

export const imStatusService = {
    dependencies: ["bus_service", "presence"],

    /**
     * @param {import("@web/env").OdooEnv} env
     * @param {{ bus_service: any, presence: any }} services
     */
    start(env, services) {
        const imStatus = new ImStatusService(env, services);
        imStatus.setup();
        return imStatus;
    },
};

registry.category("services").add("im_status", imStatusService);
