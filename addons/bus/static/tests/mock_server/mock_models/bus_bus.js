import { getWebSocketWorker } from "@bus/../tests/mock_websocket";
import { models } from "@web/../tests/web_test_helpers";

export class BusBus extends models.Model {
    _name = "bus.bus";

    /** @type {Record<number, string[]>} */
    channelsByUser = {};
    lastBusNotificationId = 0;
    // Minimal server-like store: every dispatched notification is kept as
    // `{ id, target, value }` so a (re)subscribe carrying a `last` cursor can
    // replay the gap (see `_replayForSubscribe`). The real `bus.bus` persists
    // rows and re-sends everything after `last` on subscribe; this mirrors the
    // essential behavior needed to test reconnect id-gap recovery without a
    // full DB.
    /** @type {{ id: number, target: any, value: any }[]} */
    _notificationStore = [];

    /**
     * @param {models.Model | string} channel
     * @param {string} notificationType
     * @param {any} message
     */
    _sendone(channel, notificationType, message) {
        this._sendmany([[channel, notificationType, message]]);
    }

    /** @param {[models.Model | string, string, any][]} notifications */
    _sendmany(notifications) {
        /** @type {import("mock_models").IrWebSocket} */
        const IrWebSocket = this.env["ir.websocket"];

        if (!notifications.length) {
            return;
        }
        const authenticatedUserId =
            "res.users" in this.env
                ? (this.env.cookie.get("authenticated_user_sid") ?? this.env.uid)
                : null;
        const channels = [
            ...IrWebSocket._build_bus_channel_list(
                this.channelsByUser[authenticatedUserId] || [],
            ),
        ];
        const matching = notifications.filter(([target]) =>
            this._channelMatches(channels, target),
        );
        if (matching.length === 0) {
            return;
        }
        const values = [];
        for (const notification of matching) {
            const [target, type, payload] = [
                notification[0],
                ...notification.slice(1, notification.length),
            ];
            const value = {
                id: ++this.lastBusNotificationId,
                message: { payload: JSON.parse(JSON.stringify(payload)), type },
            };
            values.push(value);
            this._notificationStore.push({ id: value.id, target, value });
        }
        this._deliver(values);
    }

    /**
     * Deliver a batch to the worker. When the socket is up, route it through
     * the worker's message path (as the real server does) so the worker tracks
     * ids for its `last` watermark and applies its seen-id dedup; otherwise
     * fall back to a direct broadcast (the worker has no live socket to receive
     * on, a mock-only shortcut).
     *
     * @param {{ id: number, message: any }[]} values
     */
    _deliver(values) {
        const worker = getWebSocketWorker();
        if (worker?.websocket && worker._isWebsocketConnected()) {
            worker.websocket.dispatchEvent(
                new MessageEvent("message", { data: JSON.stringify(values) }),
            );
        } else {
            worker?.broadcast("BUS:NOTIFICATION", values);
        }
    }

    /**
     * Whether `target` (a string channel or a record/[record, subchannel]
     * tuple) is present in the subscribed `channels` list.
     *
     * @param {any[]} channels
     * @param {models.Model | string | [models.Model, string]} target
     */
    _channelMatches(channels, target) {
        return channels.some((channel) => {
            if (typeof target === "string") {
                return channel === target;
            }
            if (Array.isArray(target) && Array.isArray(channel)) {
                const [target0, target1] = target;
                const [channel0, channel1] = channel;
                return (
                    channel0?._name === target0?.model &&
                    channel0?.id === target0?.id &&
                    channel1 === target1
                );
            }
            return channel?._name === target?.model && channel?.id === target?.id;
        });
    }

    /**
     * Re-broadcast stored notifications newer than `last` that still match the
     * current subscription. Mirrors the server replaying missed notifications
     * on (re)subscribe; the worker's own seen-id dedup drops anything the tab
     * already processed, so a replay is a no-op unless there is a genuine gap.
     *
     * NOTE ON DIVERGENCE: `last` is the aggregate worker watermark (the mock
     * worker is shared across all tabs of a test), so replay cannot be scoped
     * to a single (re)subscribing client — it broadcasts to every client and
     * relies on per-client dedup, exactly as the shared worker does for a live
     * batch.
     *
     * @param {number} [last]
     */
    _replayForSubscribe(last) {
        if (!last) {
            return;
        }
        /** @type {import("mock_models").IrWebSocket} */
        const IrWebSocket = this.env["ir.websocket"];
        const authenticatedUserId =
            "res.users" in this.env
                ? (this.env.cookie.get("authenticated_user_sid") ?? this.env.uid)
                : null;
        const channels = [
            ...IrWebSocket._build_bus_channel_list(
                this.channelsByUser[authenticatedUserId] || [],
            ),
        ];
        const values = this._notificationStore
            .filter(
                ({ id, target }) => id > last && this._channelMatches(channels, target),
            )
            .map(({ value }) => value);
        if (values.length) {
            this._deliver(values);
        }
    }

    /**
     * Close the current websocket with the given reason and code.
     *
     * @param {number} closeCode the code to close the connection with.
     * @param {string} [reason] the reason to close the connection with.
     */
    _simulateDisconnection(closeCode, reason) {
        getWebSocketWorker().websocket.close(closeCode, reason);
    }
}
