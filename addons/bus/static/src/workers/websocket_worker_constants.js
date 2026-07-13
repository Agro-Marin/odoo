/** @odoo-module native */

/**
 * Constants shared between the websocket worker and page-context code.
 *
 * Kept free of any side effect on purpose: importing `websocket_worker.js`
 * from a page (e.g. for `WORKER_STATE`) would execute worker-oriented module
 * side effects (its IndexedDB-backed logger) in every tab.
 */

/**
 * `WebSocket.readyState` values, fixed by the WHATWG spec. Named here instead
 * of using `WebSocket.OPEN`/... : test environments routinely replace the
 * `WebSocket` constructor (and even the instances) with mocks that carry none
 * of the static/prototype constants, while the numeric values can never
 * change.
 */
export const WEBSOCKET_READY_STATE = Object.freeze({
    CONNECTING: 0,
    OPEN: 1,
    CLOSING: 2,
    CLOSED: 3,
});

export const WEBSOCKET_CLOSE_CODES = Object.freeze({
    CLEAN: 1000,
    GOING_AWAY: 1001,
    PROTOCOL_ERROR: 1002,
    INCORRECT_DATA: 1003,
    ABNORMAL_CLOSURE: 1006,
    INCONSISTENT_DATA: 1007,
    MESSAGE_VIOLATING_POLICY: 1008,
    MESSAGE_TOO_BIG: 1009,
    EXTENSION_NEGOTIATION_FAILED: 1010,
    SERVER_ERROR: 1011,
    RESTART: 1012,
    TRY_LATER: 1013,
    BAD_GATEWAY: 1014,
    SESSION_EXPIRED: 4001,
    KEEP_ALIVE_TIMEOUT: 4002,
    // Server-side meaning (websocket.py CloseCode): terminate without a
    // close handshake.
    KILL_NOW: 4003,
    // Client-synthetic code (see `WebsocketWorker._start`): never sent over
    // the wire, only fed to `_onWebsocketClose` when the close event did not
    // fire.
    CLOSING_HANDSHAKE_ABORTED: 4004,
});

/** Connection state of the websocket worker (not the init lifecycle of
 * `worker_service`, which has its own, differently-valued `WORKER_STATE`). */
export const CONNECTION_STATE = Object.freeze({
    CONNECTED: "CONNECTED",
    DISCONNECTED: "DISCONNECTED",
    IDLE: "IDLE",
    CONNECTING: "CONNECTING",
});

/**
 * @deprecated Use `CONNECTION_STATE`. This alias only exists because
 * outside-bus code still imports `WORKER_STATE` (via the deprecated
 * `websocket_worker.js` re-export): `web/static/tests/tours/user_switch_tour.js`
 * and `auth_totp/static/tests/totp_flow.js`. Remove it once those import
 * `CONNECTION_STATE` from this module. The name collided with the (unrelated)
 * init-lifecycle `WORKER_STATE` of `@bus/services/worker_service`.
 */
export const WORKER_STATE = CONNECTION_STATE;
