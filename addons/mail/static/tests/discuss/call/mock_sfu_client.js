/**
 * State enum mirroring `SFU_CLIENT_STATE` of
 * `@mail/../lib/odoo_sfu/odoo_sfu.js` (which is only available through the
 * lazy "mail.assets_odoo_sfu" bundle, hence duplicated here for tests).
 */
export const MOCK_SFU_CLIENT_STATE = Object.freeze({
    DISCONNECTED: "disconnected",
    CONNECTING: "connecting",
    AUTHENTICATED: "authenticated",
    CONNECTED: "connected",
    RECOVERING: "recovering",
    CLOSED: "closed",
});

/**
 * Mirrors the event/state surface of the real SfuClient that is consumed by
 * `CallTransport` and `Network`:
 * - `state` getter/setter dispatching "stateChange" CustomEvents,
 * - "update" CustomEvents ({ name, payload }),
 * - `errors` array and `_consumers` map (read by `Network.getSfuConsumerStats`
 *   and `Rtc.buildSnapshot`),
 * - `connect`/`disconnect`/`broadcast`/`updateInfo`/`updateUpload`/
 *   `updateDownload`/`getStats` methods.
 *
 * Every method call is recorded in `calls` as `[methodName, ...args]` for
 * assertions.
 */
export class MockSfuClient extends EventTarget {
    /** @type {Error[]} */
    errors = [];
    /** @type {Map<number, Object>} consumers by session id */
    _consumers = new Map();
    /** @type {Array<Array>} recorded method calls */
    calls = [];
    _state = MOCK_SFU_CLIENT_STATE.DISCONNECTED;

    /**
     * @param {Object} [param0]
     * @param {(client: MockSfuClient) => Promise<void>} [param0.connectBehavior]
     *  overrides what `connect()` does. The default mirrors the real client:
     *  CONNECTING then AUTHENTICATED (resolving there — CONNECTED comes later,
     *  from the server-driven transport init, via `simulateConnected()`).
     */
    constructor({ connectBehavior } = {}) {
        super();
        this._connectBehavior =
            connectBehavior ??
            (async (client) => {
                client.state = MOCK_SFU_CLIENT_STATE.CONNECTING;
                client.state = MOCK_SFU_CLIENT_STATE.AUTHENTICATED;
            });
    }

    get state() {
        return this._state;
    }

    set state(state) {
        this._state = state;
        this.dispatchEvent(
            new CustomEvent("stateChange", {
                detail: { state },
            }),
        );
    }

    async connect(url, jsonWebToken, options = {}) {
        this.calls.push(["connect", url, jsonWebToken, options]);
        await this._connectBehavior(this);
    }

    disconnect() {
        this.calls.push(["disconnect"]);
        this.state = MOCK_SFU_CLIENT_STATE.DISCONNECTED;
    }

    broadcast(message) {
        this.calls.push(["broadcast", message]);
    }

    updateInfo(info, options = {}) {
        this.calls.push(["updateInfo", info, options]);
    }

    async updateUpload(type, track) {
        this.calls.push(["updateUpload", type, track]);
    }

    updateDownload(sessionId, states) {
        this.calls.push(["updateDownload", sessionId, states]);
    }

    async getStats() {
        this.calls.push(["getStats"]);
        return {};
    }

    /** Simulates the server completing the transport initialisation. */
    simulateConnected() {
        this.state = MOCK_SFU_CLIENT_STATE.CONNECTED;
    }

    /**
     * Simulates the server closing the connection (real client: `_close`,
     * which dispatches "stateChange" with a `cause`).
     *
     * @param {string} [cause] e.g. "full"
     */
    simulateClose(cause) {
        this._state = MOCK_SFU_CLIENT_STATE.CLOSED;
        this.dispatchEvent(
            new CustomEvent("stateChange", {
                detail: { state: MOCK_SFU_CLIENT_STATE.CLOSED, cause },
            }),
        );
    }

    /**
     * Simulates a server-side update (track, broadcast, disconnect,
     * info_change), like the real client's `_updateClient`.
     *
     * @param {string} name
     * @param {any} payload
     */
    simulateUpdate(name, payload) {
        this.dispatchEvent(
            new CustomEvent("update", {
                detail: { name, payload },
            }),
        );
    }
}
