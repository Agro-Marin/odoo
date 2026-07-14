import { getWebSocketWorker, onWebsocketEvent } from "@bus/../tests/mock_websocket";
import { WebsocketWorker } from "@bus/workers/websocket_worker";
import { WEBSOCKET_CLOSE_CODES } from "@bus/workers/websocket_worker_constants";
import { advanceTime, Deferred, describe, expect, test } from "@odoo/hoot";
import { runAllTimers, waitUntil } from "@odoo/hoot-dom";
import {
    asyncStep,
    makeMockServer,
    MockServer,
    patchWithCleanup,
    waitForSteps,
} from "@web/../tests/web_test_helpers";

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
    // The mock WebSocket dispatches its `open` on a task tick, so the socket may
    // still be CONNECTING here; wait for the connection to settle so callers get
    // a genuinely CONNECTED worker.
    await waitUntil(() => worker.state !== "CONNECTING");
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

test("last notification id adopts the new DB's watermark on a database change", async () => {
    // `bus_bus.id` is a per-database sequence, so the old DB's watermark must be
    // dropped. But the incoming tab's `lastNotificationId` is read from the NEW
    // DB's (db-scoped) localStorage key, so it is the correct baseline and must
    // be adopted — resetting to 0 would subscribe with `last: 0` ("from now")
    // and skip notifications committed before the resubscribe.
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
    // Switch to a different DB, carrying that DB's own watermark.
    worker._initializeConnection(client, {
        db: "db2",
        uid: 1,
        lastNotificationId: 5,
        websocketURL: worker.websocketURL,
        startTs: 2,
    });
    expect(worker.currentDB).toBe("db2");
    expect(worker.lastNotificationId).toBe(5);
    expect(worker.messageWaitQueue).toEqual([]);
    // A DB change with no known watermark for the new DB falls back to 0.
    worker._initializeConnection(client, {
        db: "db3",
        uid: 1,
        websocketURL: worker.websocketURL,
        startTs: 3,
    });
    expect(worker.lastNotificationId).toBe(0);
});

test("a uid/db switch asks every client to replay its channels", async () => {
    // Switching uid (logout/login) or db wipes every client's worker-side
    // channel map. The other tabs keep their page-side claims but are not
    // re-initialized, so without a broadcast RESYNC their channels vanish from
    // the next subscribe and never come back — a silently dead bus for those
    // tabs. Every registered client must be asked to replay its snapshot.
    const worker = await startWebSocketWorker();
    const receivedByOther = [];
    const other = {
        addEventListener: () => {},
        postMessage: (message) => receivedByOther.push(message),
    };
    const switcher = { addEventListener: () => {}, postMessage() {} };
    worker.registerClient(other);
    worker.registerClient(switcher);
    // Establish the first uid/db and give the other tab a channel claim.
    worker._initializeConnection(switcher, {
        db: "db1",
        uid: 1,
        websocketURL: worker.websocketURL,
        startTs: 1,
    });
    worker._addChannel(other, "chA");
    receivedByOther.length = 0;
    // The switcher re-initializes as a different user.
    worker._initializeConnection(switcher, {
        db: "db1",
        uid: 2,
        websocketURL: worker.websocketURL,
        startTs: 2,
    });
    expect(worker.currentUID).toBe(2);
    expect(receivedByOther.some(({ type }) => type === "BUS:RESYNC")).toBe(true);
});

test("every reconnect re-subscribes with the current channels", async () => {
    // A new connection is a fresh `Connection` whose `lastSubscription` starts
    // null, so the open-time `_updateChannels` always (re)subscribes — even when
    // the channel set is unchanged from the previous connection. This makes the
    // "always subscribe on a fresh connection" invariant structural (it used to
    // depend on nulling a worker field on every open/close/stop).
    const subscriptions = [];
    onWebsocketEvent("subscribe", ({ channels }) => subscriptions.push(channels));
    const worker = await startWebSocketWorker((type) => {
        if (["BUS:DISCONNECT", "BUS:RECONNECTING", "BUS:RECONNECT"].includes(type)) {
            asyncStep(type);
        }
    });
    const client = { postMessage() {}, addEventListener() {} };
    worker.registerClient(client);
    worker._addChannel(client, "chA");
    await runAllTimers();
    expect(subscriptions).toEqual([["chA"]]);
    // Force an unclean close → automatic reconnect, WITHOUT changing channels.
    subscriptions.length = 0;
    worker.websocket.close(WEBSOCKET_CLOSE_CODES.ABNORMAL_CLOSURE);
    await waitForSteps(["BUS:DISCONNECT", "BUS:RECONNECTING"]);
    await runAllTimers();
    await waitForSteps(["BUS:RECONNECT"]);
    // The open-time subscribe is debounced (~300ms after reopen); fire it.
    await runAllTimers();
    // The brand-new connection re-subscribed despite the unchanged channel set.
    expect(subscriptions).toEqual([["chA"]]);
});

test("a late event from a superseded socket is ignored (epoch guard)", async () => {
    // Once a newer connection replaces the socket, a straggler `message`/`close`
    // from the old socket must not act on the current connection.
    const worker = await startWebSocketWorker();
    const staleSocket = worker.websocket;
    // Supersede the connection with a different socket (mimics a new `_start`).
    worker._connection = {
        socket: { readyState: 1 },
        subscribeDeferred: new Deferred(),
        lastSubscription: null,
    };
    const broadcasts = [];
    patchWithCleanup(worker, {
        broadcast(type, ...rest) {
            broadcasts.push(type);
            return super.broadcast(type, ...rest);
        },
    });
    // A stale message from the OLD socket: ignored → no BUS:NOTIFICATION.
    worker._onWebsocketMessage({
        type: "message",
        currentTarget: staleSocket,
        data: JSON.stringify([{ id: 1, message: "x" }]),
    });
    expect(broadcasts).not.toInclude("BUS:NOTIFICATION");
    // A stale close from the OLD socket: ignored → no disconnect/reconnect.
    worker._onWebsocketClose({ type: "close", currentTarget: staleSocket, code: 1006 });
    expect(broadcasts).not.toInclude("BUS:DISCONNECT");
    expect(broadcasts).not.toInclude("BUS:RECONNECTING");
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
    // `channelsByClient` values are now `Map<channel, refcount>`, not string[].
    expect(worker.channelsByClient.get(client)).toEqual(new Map([["chA", 1]]));
    worker.broadcast("BUS:NOTIFICATION", []);
    expect(received.some(({ type }) => type === "BUS:NOTIFICATION")).toBe(true);
});

test("reconnect sends exactly one fresh subscribe and flushes queued app messages", async () => {
    // Subscribes are never queued: `_updateChannels` only subscribes on an open
    // socket (sending directly), so the wait queue holds application messages
    // only. A reconnect therefore emits exactly one fresh subscribe, then
    // flushes the queued application messages after it.
    const worker = await startWebSocketWorker();
    const client = { postMessage() {}, addEventListener() {} };
    worker.registerClient(client);
    worker._addChannel(client, "chA");
    await runAllTimers();
    worker._stop();
    // An application message sent while stopped is queued; a subscribe is not
    // (nothing subscribes while the socket is down).
    worker._sendToServer({ event_name: "some_event", data: 1 });
    expect(worker.messageWaitQueue).toHaveLength(1);
    worker._start();
    // Intercept at the socket-instance level: the open-time subscribe from
    // `_updateChannels` AND the queue flush (which calls `websocket.send`
    // directly) both go through this instance.
    const sentFrames = [];
    const ogSend = worker.websocket.send.bind(worker.websocket);
    worker.websocket.send = (message) => {
        if (typeof message === "string") {
            sentFrames.push(JSON.parse(message));
        }
        ogSend(message);
    };
    // Let the reconnect's `open` settle (dispatched on a task tick), then flush
    // the debounced open-time `_updateChannels` (fresh subscribe + queue flush).
    await waitUntil(() => worker.state !== "CONNECTING");
    await runAllTimers();
    const subscribes = sentFrames.filter((f) => f.event_name === "subscribe");
    expect(subscribes).toHaveLength(1);
    expect(subscribes[0].data.last).toBe(worker.lastNotificationId);
    // The queued application message went through, after the subscribe.
    expect(sentFrames.some((f) => f.event_name === "some_event")).toBe(true);
    expect(worker.messageWaitQueue).toHaveLength(0);
});

test("a send chained on the subscribe gate is re-queued when the connection is torn down", async () => {
    // A non-subscribe message sent on a connected-but-not-yet-subscribed socket
    // waits on the connection's subscribe gate. If the connection is stopped
    // before subscribing, resolving the gate must re-queue the message for the
    // next open — not write it to the dead/superseded socket and lose it.
    const worker = await startWebSocketWorker();
    // Connected socket whose subscribe has not gone out yet: reset the gate.
    worker._connection.subscribeDeferred = new Deferred();
    worker._sendToServer({ event_name: "some_event", data: 1 });
    worker._stop(); // resolves the gate and drops the connection
    await runAllTimers();
    expect(worker.messageWaitQueue).toEqual([
        JSON.stringify({ event_name: "some_event", data: 1 }),
    ]);
});

test("non-BUS port traffic does not resurrect a client that sent BUS:LEAVE", async () => {
    // The websocket worker sees EVERY message on the shared port, including
    // BASE:* init traffic. A client dropped via BUS:LEAVE (`bus_service.stop()`)
    // must only be re-registered by a BUS action it sends itself — not by an
    // unrelated non-BUS message, which would silently undo `stop()`.
    const worker = await startWebSocketWorker();
    const client = {
        postMessage: () => {},
        addEventListener: () => {},
    };
    worker._onClientMessage(client, { action: "BUS:ADD_CHANNEL", data: "chA" });
    expect(worker.channelsByClient.has(client)).toBe(true);
    worker._onClientMessage(client, { action: "BUS:LEAVE" });
    expect(worker.channelsByClient.has(client)).toBe(false);
    worker._onClientMessage(client, { action: "BASE:SOMETHING" });
    expect(worker.channelsByClient.has(client)).toBe(false);
    // A BUS action from the client itself re-registers it.
    worker._onClientMessage(client, { action: "BUS:ADD_CHANNEL", data: "chB" });
    expect(worker.channelsByClient.has(client)).toBe(true);
});

test("stop reports DISCONNECTED and re-queues sends pending on the first subscribe", async () => {
    const worker = await startWebSocketWorker();
    expect(worker.state).toBe("CONNECTED");
    // Connected socket whose first subscribe has not been sent yet: the
    // message below is chained on the connection's subscribe gate.
    worker._connection.subscribeDeferred = new Deferred();
    worker._sendToServer({ event_name: "some_event", data: 1 });
    worker._stop();
    // `_stop` removed the socket listeners (no close event will fire), so it
    // must itself resolve the gate (re-queueing the pending message) and
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
    // halfway mark) the sweep must drop its port while responsive clients stay.
    const worker = await startWebSocketWorker();
    const pings = [];
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
    // Nor recreate a ghost liveness entry: the sweep iterates lastSeenByClient,
    // so a ghost would be pinged (and auto-ponged) forever, never reclaimed.
    expect(worker.lastSeenByClient.has(client)).toBe(false);
});

test("non-participatory actions do not resurrect an evicted/stopped client", async () => {
    // Re-registration is an allowlist (START/ADD_CHANNEL/SET_CHANNELS/
    // INITIALIZE_CONNECTION). Actions that do not express intent to receive —
    // BUS:STOP (an `offline` event), BUS:SEND — must never bring a stopped
    // client back, or `stop()` silently stops sticking.
    const worker = await startWebSocketWorker();
    const client = { addEventListener: () => {}, postMessage: () => {} };
    worker._onClientMessage(client, { action: "BUS:ADD_CHANNEL", data: "chA" });
    worker._onClientMessage(client, { action: "BUS:LEAVE" });
    expect(worker.channelsByClient.has(client)).toBe(false);
    worker._onClientMessage(client, { action: "BUS:STOP" });
    expect(worker.channelsByClient.has(client)).toBe(false);
    worker._onClientMessage(client, {
        action: "BUS:SEND",
        data: { event_name: "some_event" },
    });
    expect(worker.channelsByClient.has(client)).toBe(false);
});

test("re-registering an evicted client requests a channel RESYNC", async () => {
    // A client evicted by the liveness sweep while its tab was frozen (Page
    // Lifecycle freeze / system suspend) resumes and sends BUS:START. The
    // worker re-registers it with an empty map and asks it to replay its
    // channels — resume fires `resume`/`visibilitychange`, never `pageshow`,
    // so this worker-driven RESYNC is the only recovery signal.
    const worker = await startWebSocketWorker();
    const received = [];
    const client = {
        addEventListener: () => {},
        postMessage: (message) => received.push(message),
    };
    worker._onClientMessage(client, { action: "BUS:ADD_CHANNEL", data: "chA" });
    worker._unregisterClient(client);
    received.length = 0;
    worker._onClientMessage(client, { action: "BUS:START" });
    expect(worker.channelsByClient.has(client)).toBe(true);
    expect(received.some(({ type }) => type === "BUS:RESYNC")).toBe(true);
});

test("an outdated worker signals OUTDATED even on the older-startTs early return", async () => {
    // Regression: the early-return path of `_initializeConnection` used to omit
    // BUS:OUTDATED, so a late/lazy tab initializing after a server upgrade got a
    // silently dead bus and could still win the main-tab election.
    const worker = await startWebSocketWorker();
    worker.active = false;
    worker.newestStartTs = 100; // a newer tab already initialized
    const received = [];
    const client = {
        addEventListener: () => {},
        postMessage: (message) => received.push(message),
    };
    worker.registerClient(client);
    worker._initializeConnection(client, {
        db: "db1",
        uid: 1,
        websocketURL: worker.websocketURL,
        startTs: 1, // older -> early return
    });
    expect(received.some(({ type }) => type === "BUS:INITIALIZED")).toBe(true);
    expect(received.some(({ type }) => type === "BUS:OUTDATED")).toBe(true);
});

test("a wall-clock jump (system suspend) does not mass-evict live clients", async () => {
    // Timers do not fire while the machine is asleep: on wake, the single
    // delayed sweep sees every client's `lastSeen` predating the sleep. It must
    // refresh their windows, not evict them all before they can send.
    const worker = await startWebSocketWorker();
    const client = { addEventListener: () => {}, postMessage: () => {} };
    worker.registerClient(client);
    const now = Date.now();
    worker.lastSeenByClient.set(client, now - worker.CLIENT_LIVENESS_TIMEOUT - 1000);
    worker._lastLivenessSweepTs = now - worker.CLIENT_LIVENESS_TIMEOUT - 5000;
    worker._sweepClientLiveness();
    expect(worker.channelsByClient.has(client)).toBe(true);
    expect(worker.lastSeenByClient.get(client)).toBe(now);
});

test("a moderate suspend (under the liveness timeout) does not evict live clients", async () => {
    // A laptop sleep of a few minutes skips sweeps without exceeding
    // CLIENT_LIVENESS_TIMEOUT. Ages still inflate by the lost time and no tab
    // could answer a ping while asleep, so a tab already past TIMEOUT/2 would
    // jump past TIMEOUT and be evicted in a single post-wake sweep. Any skipped
    // sweep interval must be treated as lost time and grant a fresh window.
    const worker = await startWebSocketWorker();
    const client = { addEventListener: () => {}, postMessage: () => {} };
    worker.registerClient(client);
    const now = Date.now();
    // Gap between one sweep interval and the full timeout: the old
    // `> CLIENT_LIVENESS_TIMEOUT` guard missed it.
    const gap = worker.CLIENT_LIVENESS_TIMEOUT - worker.CLIENT_LIVENESS_SWEEP_DELAY;
    expect(gap).toBeGreaterThan(worker.CLIENT_LIVENESS_SWEEP_DELAY * 2);
    // The client was past the half-timeout (ping) mark just before the sleep.
    worker.lastSeenByClient.set(
        client,
        now - gap - worker.CLIENT_LIVENESS_TIMEOUT / 2 - 1000,
    );
    worker._lastLivenessSweepTs = now - gap;
    worker._sweepClientLiveness();
    expect(worker.channelsByClient.has(client)).toBe(true);
    expect(worker.lastSeenByClient.get(client)).toBe(now);
});

/**
 * Feed a raw notification batch to the worker as if the server sent it, and
 * return the ids that got broadcast to the clients (deduped/filtered ones are
 * absent).
 *
 * @param {ReturnType<getWebSocketWorker>} worker
 * @param {number[]} broadcastIds sink the broadcast collector pushes into
 * @param {{ id: number }[]} batch
 */
function feedNotifications(worker, batch) {
    worker.websocket.dispatchEvent(
        new MessageEvent("message", { data: JSON.stringify(batch) }),
    );
}

test("J1: a lower unseen id after a higher one is still broadcast", async () => {
    // The server may re-deliver LOWER ids in LATER batches (its hold-back
    // window for out-of-order commits). A monotonic watermark filter would
    // silently drop them; the id-level seen check must let them through.
    const broadcast = [];
    const worker = await startWebSocketWorker((type, data) => {
        if (type === "BUS:NOTIFICATION") {
            broadcast.push(data.map((n) => n.id));
        }
    });
    feedNotifications(worker, [{ id: 5, message: { type: "t" } }]);
    feedNotifications(worker, [{ id: 3, message: { type: "t" } }]);
    expect(broadcast).toEqual([[5], [3]]);
});

test("J1: an exact-duplicate id within the retention window is dropped", async () => {
    const broadcast = [];
    const worker = await startWebSocketWorker((type, data) => {
        if (type === "BUS:NOTIFICATION") {
            broadcast.push(data.map((n) => n.id));
        }
    });
    feedNotifications(worker, [{ id: 5, message: { type: "t" } }]);
    // Same id again, still within SEEN_NOTIFICATION_RETENTION_MS: dropped, so
    // no second broadcast.
    feedNotifications(worker, [{ id: 5, message: { type: "t" } }]);
    expect(broadcast).toEqual([[5]]);
});

test("J1: the seen-id set is cleared on a database change", async () => {
    const broadcast = [];
    const worker = await startWebSocketWorker((type, data) => {
        if (type === "BUS:NOTIFICATION") {
            broadcast.push(data.map((n) => n.id));
        }
    });
    const client = { postMessage() {}, addEventListener() {} };
    worker.registerClient(client);
    worker._initializeConnection(client, {
        db: "db1",
        uid: 1,
        websocketURL: worker.websocketURL,
        startTs: 1,
    });
    feedNotifications(worker, [{ id: 5, message: { type: "t" } }]);
    expect(worker.seenNotificationIds.has(5)).toBe(true);
    // Switching DB invalidates the per-DB id sequence: the seen-set must reset
    // so a colliding id from the new DB is not wrongly dropped.
    worker._initializeConnection(client, {
        db: "db2",
        uid: 1,
        websocketURL: worker.websocketURL,
        startTs: 2,
    });
    expect(worker.seenNotificationIds.size).toBe(0);
    feedNotifications(worker, [{ id: 5, message: { type: "t" } }]);
    expect(broadcast).toEqual([[5], [5]]);
});

test("J1: seen ids older than the retention window are pruned", async () => {
    const broadcast = [];
    const worker = await startWebSocketWorker((type, data) => {
        if (type === "BUS:NOTIFICATION") {
            broadcast.push(data.map((n) => n.id));
        }
    });
    feedNotifications(worker, [{ id: 5, message: { type: "t" } }]);
    // Age id 5 past the retention window, then feed another frame (which prunes
    // at its start). Id 5 can no longer be legitimately re-sent, so it is
    // forgotten — a later id 5 would be treated as fresh again.
    await advanceTime(worker.SEEN_NOTIFICATION_RETENTION_MS + 1000);
    feedNotifications(worker, [{ id: 9, message: { type: "t" } }]);
    expect(worker.seenNotificationIds.has(5)).toBe(false);
    feedNotifications(worker, [{ id: 5, message: { type: "t" } }]);
    expect(broadcast).toEqual([[5], [9], [5]]);
});

test("J1: the seen-id set is capped at SEEN_NOTIFICATION_MAX_COUNT", async () => {
    const worker = await startWebSocketWorker();
    patchWithCleanup(worker, { SEEN_NOTIFICATION_MAX_COUNT: 3 });
    // One batch overflows the cap; the prune only runs at the NEXT frame start,
    // trimming the oldest back down to the cap BEFORE that frame's ids are
    // added (so the size settles at cap + latest-batch-size, never unbounded).
    feedNotifications(
        worker,
        [1, 2, 3, 4, 5].map((id) => ({ id, message: { type: "t" } })),
    );
    expect(worker.seenNotificationIds.size).toBe(5);
    feedNotifications(worker, [{ id: 6, message: { type: "t" } }]);
    // Pruned back to cap (3) then id 6 added -> 4; the oldest ids were evicted.
    expect(worker.seenNotificationIds.size).toBe(4);
    expect(worker.seenNotificationIds.has(1)).toBe(false);
    expect(worker.seenNotificationIds.has(2)).toBe(false);
    expect(worker.seenNotificationIds.has(6)).toBe(true);
});

test("J2: per-client channel refcount keeps the channel until fully released", async () => {
    const worker = await startWebSocketWorker();
    const client = { postMessage() {}, addEventListener() {} };
    worker.registerClient(client);
    worker._addChannel(client, "chA");
    worker._addChannel(client, "chA");
    expect(worker.channelsByClient.get(client)).toEqual(new Map([["chA", 2]]));
    worker._deleteChannel(client, "chA");
    // One claim remains: the channel stays.
    expect(worker._getAllChannels()).toEqual(["chA"]);
    worker._deleteChannel(client, "chA");
    expect(worker._getAllChannels()).toEqual([]);
});

test("J2: BUS:SET_CHANNELS replaces the map atomically and drops count<=0", async () => {
    const worker = await startWebSocketWorker();
    const client = { postMessage() {}, addEventListener() {} };
    worker.registerClient(client);
    worker._addChannel(client, "old");
    worker._setChannels(client, [
        ["chA", 2],
        ["chB", 1],
        ["dropped", 0],
        ["negative", -3],
    ]);
    // "old" is gone (atomic replace), count<=0 entries are not kept.
    expect(worker.channelsByClient.get(client)).toEqual(
        new Map([
            ["chA", 2],
            ["chB", 1],
        ]),
    );
});

test("J4: BUS:STOP after a scheduled retry prevents the reconnect", async () => {
    const worker = await startWebSocketWorker((type) => {
        if (["BUS:CONNECT", "BUS:RECONNECT", "BUS:RECONNECTING"].includes(type)) {
            asyncStep(type);
        }
    });
    await waitForSteps(["BUS:CONNECT"]);
    // Abnormal close schedules an exponential-backoff retry.
    worker.websocket.close(WEBSOCKET_CLOSE_CODES.ABNORMAL_CLOSURE);
    await waitForSteps(["BUS:RECONNECTING"]);
    // A BUS:STOP (e.g. going offline) must cancel that pending timer.
    worker._stop();
    await runAllTimers();
    // The retry never fired: no reconnection, socket stays down.
    await waitForSteps([]);
    expect(worker.websocket).toBe(null);
    expect(worker.state).toBe("DISCONNECTED");
});

test("S3: reconnect delay backs off from the 0 fast-path to INITIAL then x1.5, capped", async () => {
    const worker = await startWebSocketWorker();
    // Isolate the backoff math from an actual (re)connection, which would reset
    // the base to INITIAL on open.
    patchWithCleanup(worker, { _start() {} });
    expect(worker.INITIAL_RECONNECT_DELAY).toBeGreaterThan(0);
    // 0 fast-path (set on keep-alive / aborted closes): the base advances to
    // INITIAL rather than hot-looping at 0.
    worker.connectRetryDelay = 0;
    worker._retryConnectionWithDelay();
    expect(worker.connectRetryDelay).toBe(worker.INITIAL_RECONNECT_DELAY);
    // Exponential growth x1.5 from there.
    worker._retryConnectionWithDelay();
    expect(worker.connectRetryDelay).toBe(worker.INITIAL_RECONNECT_DELAY * 1.5);
    worker._retryConnectionWithDelay();
    expect(worker.connectRetryDelay).toBe(worker.INITIAL_RECONNECT_DELAY * 1.5 * 1.5);
    // Cap at MAXIMUM_RECONNECT_DELAY (60_000).
    worker.connectRetryDelay = 50_000;
    worker._retryConnectionWithDelay();
    expect(worker.connectRetryDelay).toBe(60_000);
    worker._retryConnectionWithDelay();
    expect(worker.connectRetryDelay).toBe(60_000);
});

test("worker answers BUS:PING probes... only pings silent clients", async () => {
    // Guardrail companion to the liveness-sweep test: a freshly-seen client is
    // NOT pinged (only clients silent past half the timeout are).
    const worker = await startWebSocketWorker();
    const pinged = [];
    const client = {
        addEventListener: () => {},
        postMessage: (message) => {
            if (message.type === "BUS:PING") {
                pinged.push(client);
            }
        },
    };
    worker.registerClient(client);
    worker._sweepClientLiveness();
    expect(pinged).toEqual([]);
});
