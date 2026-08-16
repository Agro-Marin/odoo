export const MOCK_SFU_CLIENT_STATE = Object.freeze({
    DISCONNECTED: "disconnected",
    CONNECTING: "connecting",
    AUTHENTICATED: "authenticated",
    CONNECTED: "connected",
    RECOVERING: "recovering",
    CLOSED: "closed",
});

export class MockSfuClient extends EventTarget {
    /** @type {Error[]} */
    errors = [];
    /** @type {Map<number, Object>} */
    _consumers = new Map();
    /** @type {Array<Array>} */
    calls = [];
    _state = MOCK_SFU_CLIENT_STATE.DISCONNECTED;

    /**
     * @param {Object} [param0]
     * @param {(client: MockSfuClient) => Promise<void>} [param0.connectBehavior]
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

    simulateConnected() {
        this.state = MOCK_SFU_CLIENT_STATE.CONNECTED;
    }

    /** @param {string} [cause] */
    simulateClose(cause) {
        this._state = MOCK_SFU_CLIENT_STATE.CLOSED;
        this.dispatchEvent(
            new CustomEvent("stateChange", {
                detail: { state: MOCK_SFU_CLIENT_STATE.CLOSED, cause },
            }),
        );
    }

    /**
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
