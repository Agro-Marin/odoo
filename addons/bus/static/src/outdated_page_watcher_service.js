/** @odoo-module native */
import { lastNotificationIdKey } from "@bus/services/bus_service";
import { CONNECTION_STATE } from "@bus/workers/websocket_worker_constants";
import { browser } from "@web/core/browser/browser";
import { _t } from "@web/core/l10n/translation";
import { rpc } from "@web/core/network/rpc";
import { registry } from "@web/core/registry";
import { session } from "@web/session";

/**
 * Key of the cross-tab shared flag recording that notifications were missed.
 *
 * Scoped by database for the same reason as `lastNotificationIdKey`:
 * `bus_bus.id` is a per-database sequence, so on a multi-database origin a
 * flag raised by another database's tabs would show a false "page is out of
 * date" warning here.
 */
export function hasMissedNotificationsKey() {
    return `${session.db}.bus.has_missed_notifications`;
}

export class OutdatedPageWatcherService {
    constructor(env, services) {
        this.setup(env, services);
    }

    /**
     * @param {import("@web/env").OdooEnv}
     * @param {Partial<import("services").Services>} services
     */
    setup(env, { bus_service, multi_tab, legacy_multi_tab, notification }) {
        this.notification = notification;
        this.multi_tab = multi_tab;
        this.legacy_multi_tab = legacy_multi_tab;
        this.lastNotificationId = legacy_multi_tab.getSharedValue(
            lastNotificationIdKey(),
        );
        this.closeNotificationFn = undefined;
        let wasBusAlreadyConnected;
        bus_service.addEventListener(
            "BUS:WORKER_STATE_UPDATED",
            ({ detail: state }) => {
                // Only CONNECTED proves a PREVIOUS connection existed. Neither
                // CONNECTING nor DISCONNECTED does: on a browser session
                // restore (or a restore while the server is down/restarting),
                // a joining tab replays the worker's current state, which is
                // CONNECTING *or* DISCONNECTED (every failed attempt and every
                // `_stop()` broadcasts DISCONNECTED — see
                // `websocket_worker._onWebsocketClose`/`_stop`). Treating
                // either as "already connected" would compare yesterday's
                // localStorage watermark against the server (whose bus_bus
                // rows are long GC'd) — a guaranteed, sticky false "page is
                // out of date", propagated to every tab via the shared flag.
                // A tab joining during a real reconnect is still covered by
                // the BUS:CONNECT/BUS:RECONNECT listeners below.
                wasBusAlreadyConnected = state === CONNECTION_STATE.CONNECTED;
            },
            { once: true },
        );
        // The transport layer only does the multi-tab bookkeeping on
        // BUS:OUTDATED (see bus_service): this service owns the single,
        // deduped (via `closeNotificationFn`) user-facing notification for
        // every "page is outdated" trigger.
        bus_service.addEventListener("BUS:OUTDATED", () =>
            this.showOutdatedPageNotification(),
        );
        bus_service.addEventListener(
            "BUS:DISCONNECT",
            () =>
                (this.lastNotificationId = legacy_multi_tab.getSharedValue(
                    lastNotificationIdKey(),
                )),
        );
        bus_service.addEventListener("BUS:CONNECT", async () => {
            if (wasBusAlreadyConnected) {
                this.checkHasMissedNotifications();
            }
            wasBusAlreadyConnected = true;
        });
        bus_service.addEventListener("BUS:RECONNECT", () => {
            // Same guard as BUS:CONNECT: the worker broadcasts BUS:RECONNECT
            // whenever `isReconnecting` is set, which ANY failed attempt sets —
            // including the retry of a first-ever connection. Probing then would
            // compare a stale (possibly GC'd) watermark against the server and
            // raise a sticky false "page is out of date". A genuine reconnect
            // always had a prior BUS:CONNECT, so `wasBusAlreadyConnected` is the
            // right discriminator.
            if (wasBusAlreadyConnected) {
                this.checkHasMissedNotifications();
            }
            wasBusAlreadyConnected = true;
        });
        legacy_multi_tab.bus.addEventListener(
            "shared_value_updated",
            ({ detail: { key } }) => {
                if (key === hasMissedNotificationsKey()) {
                    this.showOutdatedPageNotification();
                }
            },
        );
    }

    async checkHasMissedNotifications() {
        if (!this.lastNotificationId || !(await this.multi_tab.isOnMainTab())) {
            return;
        }
        const hasMissedNotifications = await rpc(
            "/bus/has_missed_notifications",
            { last_notification_id: this.lastNotificationId },
            { silent: true },
        );
        if (hasMissedNotifications) {
            this.showOutdatedPageNotification();
            this.legacy_multi_tab.setSharedValue(
                hasMissedNotificationsKey(),
                Date.now(),
            );
        }
    }

    showOutdatedPageNotification() {
        this.closeNotificationFn?.();
        this.closeNotificationFn = this.notification.add(
            _t(
                "Save your work and refresh to get the latest updates and avoid potential issues.",
            ),
            {
                title: _t("The page is out of date"),
                type: "warning",
                sticky: true,
                buttons: [
                    {
                        name: _t("Refresh"),
                        primary: true,
                        onClick: () => browser.location.reload(),
                    },
                ],
            },
        );
    }
}

export const outdatedPageWatcherService = {
    dependencies: ["bus_service", "multi_tab", "legacy_multi_tab", "notification"],
    start(env, services) {
        return new OutdatedPageWatcherService(env, services);
    },
};

registry
    .category("services")
    .add("bus.outdated_page_watcher", outdatedPageWatcherService);
