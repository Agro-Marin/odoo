import { getWebSocketWorker, onWebsocketEvent } from "@bus/../tests/mock_websocket";
import { advanceTime, Deferred, describe, expect, test } from "@odoo/hoot";
import { runAllTimers } from "@odoo/hoot-dom";
import {
    asyncStep,
    makeMockServer,
    MockServer,
    patchWithCleanup,
    waitForSteps,
} from "@web/../tests/web_test_helpers";

import { WEBSOCKET_CLOSE_CODES, WebsocketWorker } from "@bus/workers/websocket_worker";

describe.current.tags("headless");

/**
 * @param {ReturnType<getWebSocketWorker>} worker
 * @param {(type: string, message: any) => any} [onBroadcast]
 */
const startWebSocketWorker = async (onBroadcast) => {
    await makeMockServer();
    const worker = getWebSocketWorker();
    if (onBroadcast) {
        patchWithCleanup(worker, {
            broadcast(...args) {
                onBroadcast(...args);
                return super.broadcast(...args);
            },
        });
    }
    worker._start();
    await runAllTimers();
    return worker;
};

test("connect event is broadcasted after calling start", async () => {
    await startWebSocketWorker((type) => {
        if (type !== "BUS:WORKER_STATE_UPDATED") {
            asyncStep(`broadcast ${type}`);
        }
    });
    await waitForSteps(["broadcast BUS:CONNECT"]);
});

test("disconnect event is broadcasted", async () => {
    const worker = await startWebSocketWorker((type) => {
        if (type !== "BUS:WORKER_STATE_UPDATED") {
            asyncStep(`broadcast ${type}`);
        }
    });
    await waitForSteps(["broadcast BUS:CONNECT"]);
    worker.websocket.close(WEBSOCKET_CLOSE_CODES.CLEAN);
    await runAllTimers();
    await waitForSteps(["broadcast BUS:DISCONNECT"]);
});

test("reconnecting/reconnect event is broadcasted", async () => {
    const worker = await startWebSocketWorker((type) => {
        if (type !== "BUS:WORKER_STATE_UPDATED") {
            asyncStep(`broadcast ${type}`);
        }
    });
    await waitForSteps(["broadcast BUS:CONNECT"]);
    worker.websocket.close(WEBSOCKET_CLOSE_CODES.ABNORMAL_CLOSURE);
    await waitForSteps(["broadcast BUS:DISCONNECT", "broadcast BUS:RECONNECTING"]);
    await runAllTimers();
    await waitForSteps(["broadcast BUS:RECONNECT"]);
});

test("notification event is broadcasted", async () => {
    const notifications = [
        {
            id: 70,
            message: {
                type: "bundle_changed",
                payload: {
                    server_version: "15.5alpha1+e",
                },
            },
        },
    ];
    await startWebSocketWorker((type, message) => {
        if (type === "BUS:NOTIFICATION") {
            expect(message).toEqual(notifications);
        }
        if (["BUS:CONNECT", "BUS:NOTIFICATION"].includes(type)) {
            asyncStep(`broadcast ${type}`);
        }
    });
    await waitForSteps(["broadcast BUS:CONNECT"]);
    for (const serverWs of MockServer.current._websockets) {
        serverWs.send(JSON.stringify(notifications));
    }
    await waitForSteps(["broadcast BUS:NOTIFICATION"]);
});

test("non-array JSON frame is ignored, not thrown on", async () => {
    // A frame that is valid JSON but not a notification array (e.g. an echoed
    // control frame) must be ignored rather than throwing out of the message
    // listener on `payload.filter`. Regression test for the `Array.isArray`
    // guard in `_onWebsocketMessage`.
    const notifications = [{ id: 71, message: { type: "bundle_changed" } }];
    const worker = await startWebSocketWorker((type) => {
        if (["BUS:CONNECT", "BUS:NOTIFICATION"].includes(type)) {
            asyncStep(`broadcast ${type}`);
        }
    });
    await waitForSteps(["broadcast BUS:CONNECT"]);
    // Non-array JSON payloads: an object and a bare number. Neither should
    // throw nor broadcast a notification.
    for (const frame of ['{"foo": "bar"}', "123", '"a string"']) {
        worker.websocket.dispatchEvent(new MessageEvent("message", { data: frame }));
    }
    await runAllTimers();
    // The worker is still alive and processes a subsequent valid batch.
    for (const serverWs of MockServer.current._websockets) {
        serverWs.send(JSON.stringify(notifications));
    }
    await waitForSteps(["broadcast BUS:NOTIFICATION"]);
});

test("disconnect event is sent when stopping the worker", async () => {
    const worker = await startWebSocketWorker((type) => {
        if (type !== "BUS:WORKER_STATE_UPDATED") {
            expect.step(`broadcast ${type}`);
        }
    });
    await expect.waitForSteps(["broadcast BUS:CONNECT"]);
    worker._stop();
    await runAllTimers();
    await expect.waitForSteps(["broadcast BUS:DISCONNECT"]);
});

test("check connection health during inactivity", async () => {
    const ogSocket = window.WebSocket;
    let waitingForCheck = true;
    patchWithCleanup(window, {
        WebSocket: function () {
            const ws = new ogSocket(...arguments);
            ws.send = (message) => {
                if (waitingForCheck && message instanceof Uint8Array) {
                    expect.step("check_connection_health_sent");
                    waitingForCheck = false;
                }
            };
            return ws;
        },
    });
    patchWithCleanup(WebsocketWorker.prototype, {
        enableCheckInterval: true,
        _restartConnectionCheckInterval() {
            expect.step("_restartConnectionCheckInterval");
            super._restartConnectionCheckInterval();
        },
        _sendToServer(payload) {
            if (payload.event_name === "foo") {
                super._sendToServer(payload);
            }
        },
    });
    const worker = await startWebSocketWorker((type) => {
        if (type === "BUS:CONNECT") {
            expect.step(`broadcast ${type}`);
        }
    });
    await expect.waitForSteps([
        "broadcast BUS:CONNECT",
        "_restartConnectionCheckInterval",
    ]);
    worker.websocket.dispatchEvent(
        new MessageEvent("message", {
            data: JSON.stringify([{ id: 70, message: { type: "foo" } }]),
        }),
    );
    await expect.waitForSteps(["_restartConnectionCheckInterval"]);
    worker._sendToServer({ event_name: "foo" });
    await expect.waitForSteps(["_restartConnectionCheckInterval"]);
    await advanceTime(worker.CONNECTION_CHECK_DELAY + 1000);
    await expect.waitForSteps(["check_connection_health_sent"]);
});

test("last notification id is reset when the database changes", async () => {
    // `bus_bus.id` is a per-database sequence, so a watermark carried over from
    // another DB would filter out every notification from the new (lower-id) DB.
    // Regression test for the reset in `_initializeConnection`'s DB-change branch.
    const worker = await startWebSocketWorker();
    const client = { postMessage() {}, addEventListener() {} };
    worker.registerClient(client);
    // First DB: establish `currentDB` and a high watermark + a stale queued msg.
    worker._initializeConnection(client, {
        db: "db1",
        uid: 1,
        websocketURL: worker.websocketURL,
        startTs: 1,
    });
    worker.lastNotificationId = 100;
    worker.messageWaitQueue = ["stale-from-db1"];
    // Switch to a different DB.
    worker._initializeConnection(client, {
        db: "db2",
        uid: 1,
        websocketURL: worker.websocketURL,
        startTs: 2,
    });
    expect(worker.currentDB).toBe("db2");
    expect(worker.lastNotificationId).toBe(0);
    expect(worker.messageWaitQueue).toEqual([]);
});

test("open re-subscribes even when lastChannelSubscription already matches", async () => {
    // Regression for the `lastChannelSubscription` reset in `_onWebsocketOpen`.
    // A channel change *during* a disconnect makes the debounced `_updateChannels`
    // run while offline and set `lastChannelSubscription` to the current channel
    // set. At the next `open`, the open-time `_updateChannels` would then see no
    // change, emit no subscribe and never resolve `firstSubscribeDeferred` --
    // leaving the socket connected-but-unsubscribed, silently dropping every
    // notification. `_onWebsocketOpen` must force a fresh subscribe regardless.
    const subscriptions = [];
    onWebsocketEvent("subscribe", ({ channels }) => subscriptions.push(channels));
    const worker = await startWebSocketWorker();
    const client = { postMessage() {}, addEventListener() {} };
    worker.registerClient(client);
    worker._addChannel(client, "chA");
    await runAllTimers();
    // Reproduce the post-disconnect state: the channel set is present AND
    // `lastChannelSubscription` already equals it (as a stale offline
    // `_updateChannels` leaves it just before reconnect).
    worker.lastChannelSubscription = JSON.stringify(["chA"]);
    subscriptions.length = 0;
    // Re-open the (still-live mock) connection and let the open-time debounce run.
    worker._onWebsocketOpen();
    await runAllTimers();
    // Without the reset this stays empty (no subscribe emitted on open).
    expect(subscriptions).toEqual([["chA"]]);
    expect(worker.lastChannelSubscription).toBe(JSON.stringify(["chA"]));
});

test("client that sent BUS:LEAVE can come back", async () => {
    // `bus_service.stop()` sends BUS:LEAVE, dropping the client from
    // `channelsByClient`. A later `start()`/`addChannel()` from the same
    // (still alive) port must re-register it: without the re-registration,
    // BUS:ADD_CHANNEL crashes on the missing channel list and the tab stays
    // permanently deaf to broadcasts.
    const worker = await startWebSocketWorker();
    const received = [];
    const client = {
        postMessage: (message) => received.push(message),
        addEventListener() {},
    };
    worker.registerClient(client);
    worker._onClientMessage(client, { action: "BUS:LEAVE" });
    expect(worker.channelsByClient.has(client)).toBe(false);
    worker._onClientMessage(client, { action: "BUS:ADD_CHANNEL", data: "chA" });
    await runAllTimers();
    expect(worker.channelsByClient.get(client)).toEqual(["chA"]);
    worker.broadcast("BUS:NOTIFICATION", []);
    expect(received.some(({ type }) => type === "BUS:NOTIFICATION")).toBe(true);
});

test("stale queued subscribe is not replayed on reconnect", async () => {
    // A subscribe queued while offline is stale by the time the queue is
    // flushed: the flush only runs after `_updateChannels` sent a fresh
    // subscribe for the new connection. Replaying the stale one would rewind
    // the subscription (old `last`) and trigger a pointless server re-poll.
    const worker = await startWebSocketWorker();
    worker._stop();
    // Messages sent while offline are queued; subscribes go to the front.
    worker._sendToServer({ event_name: "some_event", data: 1 });
    worker._sendToServer({
        event_name: "subscribe",
        data: { channels: ["chA"], last: 42 },
    });
    worker._start();
    // Intercept at the socket-instance level: everything the worker puts on
    // the wire — the open-time subscribe from `_updateChannels` AND the
    // queue flush (which calls `websocket.send` directly, bypassing
    // `_sendToServer`) — goes through this instance. Patching the WebSocket
    // constructor instead is unreliable here: the mock server installs its
    // own constructor and the worker module may resolve `WebSocket` from a
    // different realm than the test's `window`.
    const sentFrames = [];
    const ogSend = worker.websocket.send.bind(worker.websocket);
    worker.websocket.send = (message) => {
        if (typeof message === "string") {
            sentFrames.push(JSON.parse(message));
        }
        ogSend(message);
    };
    // Two rounds: `runAllTimers` only advances to the horizon of timers armed
    // when it is called. The first round fires the socket's `open`, which THEN
    // arms the debounced `_updateChannels` (300ms); the second round fires it
    // (fresh subscribe + queue flush).
    await runAllTimers();
    await runAllTimers();
    const subscribes = sentFrames.filter((f) => f.event_name === "subscribe");
    // Only the fresh open-time subscribe went out; the stale one (last: 42)
    // was dropped at flush time.
    expect(subscribes).toHaveLength(1);
    expect(subscribes[0].data.last).toBe(worker.lastNotificationId);
    // The queued application message still went through, after the subscribe.
    expect(sentFrames.some((f) => f.event_name === "some_event")).toBe(true);
    expect(worker.messageWaitQueue).toHaveLength(0);
});

test("pending message is requeued when subscribe deferred resolves while stopped", async () => {
    // `_updateChannels` also resolves `firstSubscribeDeferred` while offline
    // (its subscribe goes to the wait queue). A non-subscribe message chained
    // on that deferred must then be re-queued for the next open — not crash
    // with an unhandled rejection on the nulled socket and get lost.
    const worker = await startWebSocketWorker();
    // Connected socket whose first subscribe has not been sent yet.
    worker.firstSubscribeDeferred = new Deferred();
    worker._sendToServer({ event_name: "some_event", data: 1 });
    worker._stop();
    worker.firstSubscribeDeferred.resolve();
    await runAllTimers();
    expect(worker.messageWaitQueue).toEqual([
        JSON.stringify({ event_name: "some_event", data: 1 }),
    ]);
});

test("election traffic does not resurrect a client that sent BUS:LEAVE", async () => {
    // The websocket worker sees EVERY message on the shared port, including
    // ELECTION:*/BASE:* traffic. A client dropped via BUS:LEAVE
    // (`bus_service.stop()`) must only be re-registered by a BUS action it
    // sends itself — not by the election heartbeat the main tab emits every
    // 1.5s, which would silently undo `stop()`.
    const worker = await startWebSocketWorker();
    const client = {
        postMessage: () => {},
        addEventListener: () => {},
    };
    worker._onClientMessage(client, { action: "BUS:ADD_CHANNEL", data: "chA" });
    expect(worker.channelsByClient.has(client)).toBe(true);
    worker._onClientMessage(client, { action: "BUS:LEAVE" });
    expect(worker.channelsByClient.has(client)).toBe(false);
    worker._onClientMessage(client, { action: "ELECTION:HEARTBEAT" });
    expect(worker.channelsByClient.has(client)).toBe(false);
    // A BUS action from the client itself re-registers it.
    worker._onClientMessage(client, { action: "BUS:ADD_CHANNEL", data: "chB" });
    expect(worker.channelsByClient.has(client)).toBe(true);
});

test("stop reports DISCONNECTED and re-queues sends pending on the first subscribe", async () => {
    const worker = await startWebSocketWorker();
    expect(worker.state).toBe("CONNECTED");
    // Connected socket whose first subscribe has not been sent yet: the
    // message below is chained on `firstSubscribeDeferred`.
    worker.firstSubscribeDeferred = new Deferred();
    worker._sendToServer({ event_name: "some_event", data: 1 });
    worker._stop();
    // `_stop` removed the socket listeners (no close event will fire), so it
    // must itself resolve the deferred (re-queueing the pending message) and
    // report DISCONNECTED to newly opened tabs.
    await runAllTimers();
    expect(worker.state).toBe("DISCONNECTED");
    expect(worker.messageWaitQueue).toEqual([
        JSON.stringify({ event_name: "some_event", data: 1 }),
    ]);
});

test("liveness sweep pings silent clients and evicts dead ones", async () => {
    // A crashed/OOM-killed tab never sends BUS:LEAVE: after
    // CLIENT_LIVENESS_TIMEOUT of silence (with an unanswered BUS:PING at the
    // halfway mark) the sweep must drop its port — and notify the election
    // worker via `onClientEvicted` — while responsive clients stay.
    const worker = await startWebSocketWorker();
    const pings = [];
    const evicted = [];
    worker.onClientEvicted = (client) => evicted.push(client);
    const liveClient = {
        addEventListener: () => {},
        postMessage: (message) => {
            if (message.type === "BUS:PING") {
                pings.push("live");
                worker._onClientMessage(liveClient, { action: "BUS:PONG" });
            }
        },
    };
    const deadClient = {
        addEventListener: () => {},
        postMessage: (message) => {
            if (message.type === "BUS:PING") {
                pings.push("dead");
            }
        },
    };
    worker.registerClient(liveClient);
    worker.registerClient(deadClient);
    const pastPingThreshold = Date.now() - worker.CLIENT_LIVENESS_TIMEOUT / 2 - 1000;
    worker.lastSeenByClient.set(liveClient, pastPingThreshold);
    worker.lastSeenByClient.set(deadClient, pastPingThreshold);
    worker._sweepClientLiveness();
    // Both got pinged; the live one answered (BUS:PONG refreshed its
    // lastSeen), the dead one stayed silent.
    expect(pings.sort()).toEqual(["dead", "live"]);
    worker.lastSeenByClient.set(
        deadClient,
        Date.now() - worker.CLIENT_LIVENESS_TIMEOUT - 1000,
    );
    worker._sweepClientLiveness();
    expect(worker.channelsByClient.has(deadClient)).toBe(false);
    expect(worker.lastSeenByClient.has(deadClient)).toBe(false);
    expect(worker.channelsByClient.has(liveClient)).toBe(true);
    expect(evicted).toEqual([deadClient]);
});

test("BUS:PONG proves liveness but does not resurrect an evicted client", async () => {
    const worker = await startWebSocketWorker();
    const client = { addEventListener: () => {}, postMessage: () => {} };
    worker._onClientMessage(client, { action: "BUS:ADD_CHANNEL", data: "chA" });
    expect(worker.channelsByClient.has(client)).toBe(true);
    worker._unregisterClient(client);
    // A pong racing the eviction must not re-register the client with an
    // empty channel list while its tab still believes it is subscribed.
    worker._onClientMessage(client, { action: "BUS:PONG" });
    expect(worker.channelsByClient.has(client)).toBe(false);
});
