import {
    MOCK_SFU_CLIENT_STATE,
    MockSfuClient,
} from "@mail/../tests/discuss/call/mock_sfu_client";
import {
    CallTransport,
    CONNECTION_TYPES,
} from "@mail/discuss/call/common/call_transport";
import { describe, expect, test } from "@odoo/hoot";
import { advanceTime } from "@odoo/hoot-mock";
import { Deferred } from "@web/core/utils/concurrency";

describe.current.tags("desktop");

const SERVER_INFO = {
    url: "https://sfu.test",
    jsonWebToken: "jwt",
    channelUUID: "channel-uuid",
};

/**
 * Minimal PeerToPeer stand-in: `Network` only needs the EventTarget API plus
 * the upload/download/info/peer methods; every call is recorded.
 */
class MockP2p extends EventTarget {
    calls = [];
    connect(...args) {
        this.calls.push(["connect", ...args]);
    }
    disconnect() {
        this.calls.push(["disconnect"]);
    }
    addPeer(...args) {
        this.calls.push(["addPeer", ...args]);
    }
    removePeer(...args) {
        this.calls.push(["removePeer", ...args]);
    }
    removeALlPeers() {
        this.calls.push(["removeALlPeers"]);
    }
    async updateUpload(...args) {
        this.calls.push(["updateUpload", ...args]);
    }
    updateDownload(...args) {
        this.calls.push(["updateDownload", ...args]);
    }
    updateInfo(...args) {
        this.calls.push(["updateInfo", ...args]);
    }
}

/**
 * Headless CallTransport harness: plain shared state, recording hooks, a mock
 * p2p service and an injectable SfuClient factory.
 */
function makeTransport({ loadSfuClient, peerSessionIds = [] } = {}) {
    const p2p = new MockP2p();
    const state = {
        connectionType: undefined,
        fallbackMode: false,
        channel: { id: 5, rtc_session_ids: [] },
    };
    const steps = {
        connectionStates: [],
        logs: [],
        notifications: [],
        updateUpload: 0,
        leaveCall: 0,
        networkUpdates: [],
    };
    const transport = new CallTransport({
        getP2p: () => p2p,
        state,
        loadSfuClient,
        hooks: {
            getIceServers: () => [],
            getFreshInfo: () => ({ isTalking: false }),
            getPeerSessionIds: () => peerSessionIds,
            setLocalConnectionState: (connectionState) =>
                steps.connectionStates.push(connectionState),
            updateUpload: () => steps.updateUpload++,
            onNetworkUpdate: (ev) => steps.networkUpdates.push(ev.detail),
            onNetworkLog: () => {},
            log: (entry) => steps.logs.push(entry),
            notify: (text) => steps.notifications.push(text),
            leaveCall: () => steps.leaveCall++,
        },
    });
    return { transport, p2p, state, steps };
}

function sfuFactory(sfuClient) {
    return async () => ({ sfuClient, SFU_CLIENT_STATE: MOCK_SFU_CLIENT_STATE });
}

test("SFU connect reaches CONNECTED and clears the watchdog", async () => {
    const sfu = new MockSfuClient();
    const { transport, p2p, state, steps } = makeTransport({
        loadSfuClient: sfuFactory(sfu),
    });
    transport.serverInfo = SERVER_INFO;
    await transport.initConnection({ sessionId: 1, channelId: 5 });
    expect(state.connectionType).toBe(CONNECTION_TYPES.SERVER);
    expect(transport.sfuClient).toBe(sfu);
    expect(transport.network.sfu).toBe(sfu);
    expect(sfu.calls.filter(([name]) => name === "connect")).toHaveLength(1);
    expect(sfu.calls[0][1]).toBe(SERVER_INFO.url);
    // AUTHENTICATED clears the p2p peers as late as possible and broadcasts
    // the new sequence
    expect(steps.connectionStates).toInclude(MOCK_SFU_CLIENT_STATE.AUTHENTICATED);
    expect(p2p.calls.map(([name]) => name)).toInclude("removeALlPeers");
    expect(sfu.calls.some(([name]) => name === "broadcast")).toBe(true);
    const uploadsBeforeConnected = steps.updateUpload;
    sfu.simulateConnected();
    expect(steps.connectionStates.at(-1)).toBe(MOCK_SFU_CLIENT_STATE.CONNECTED);
    // CONNECTED refreshes the session info and fans the tracks out
    expect(
        sfu.calls.some(
            ([name, , options]) => name === "updateInfo" && options?.needRefresh,
        ),
    ).toBe(true);
    expect(steps.updateUpload).toBe(uploadsBeforeConnected + 1);
    // the 10s watchdog was cleared by CONNECTED: no late downgrade
    await advanceTime(15000);
    expect(state.connectionType).toBe(CONNECTION_TYPES.SERVER);
    expect(state.fallbackMode).toBe(false);
});

test("SFU load failure falls back to p2p and still calls the peers", async () => {
    const { transport, p2p, state, steps } = makeTransport({
        loadSfuClient: async () => {
            throw new Error("bundle unavailable");
        },
        peerSessionIds: [2, 3],
    });
    transport.serverInfo = SERVER_INFO;
    await transport.initConnection({ sessionId: 1, channelId: 5 });
    expect(state.connectionType).toBe(CONNECTION_TYPES.P2P);
    expect(state.fallbackMode).toBe(true);
    expect(transport.sfuClient).toBe(undefined);
    expect(steps.notifications).toHaveLength(1);
    const addPeerCalls = p2p.calls.filter(([name]) => name === "addPeer");
    expect(addPeerCalls.map(([, id]) => id)).toEqual([2, 3]);
    // both offers of the batch share the same sequence number
    expect(addPeerCalls[0][2].sequence).toBe(addPeerCalls[1][2].sequence);
});

test("SFU connect rejection downgrades to p2p exactly once", async () => {
    const sfu = new MockSfuClient({
        connectBehavior: async () => {
            throw new Error("connection refused");
        },
    });
    const { transport, state, steps } = makeTransport({
        loadSfuClient: sfuFactory(sfu),
        peerSessionIds: [2],
    });
    transport.serverInfo = SERVER_INFO;
    await transport.initConnection({ sessionId: 1, channelId: 5 });
    expect(state.connectionType).toBe(CONNECTION_TYPES.P2P);
    expect(state.fallbackMode).toBe(true);
    expect(transport.serverInfo).toBe(undefined);
    expect(transport.sfuClient).toBe(undefined);
    expect(transport.network.sfu).toBe(undefined);
    expect(sfu.calls.map(([name]) => name)).toInclude("disconnect");
    // single funnel: a second downgrade (e.g. the watchdog firing for the
    // same failure) is a no-op
    const uploads = steps.updateUpload;
    await transport.downgrade();
    expect(steps.updateUpload).toBe(uploads);
    expect(state.connectionType).toBe(CONNECTION_TYPES.P2P);
});

test("SFU connection timeout downgrades to p2p", async () => {
    const sfu = new MockSfuClient({
        connectBehavior: () => new Promise(() => {}), // hangs forever
    });
    const { transport, state, steps } = makeTransport({
        loadSfuClient: sfuFactory(sfu),
    });
    transport.serverInfo = SERVER_INFO;
    transport.initConnection({ sessionId: 1, channelId: 5 });
    await Promise.resolve(); // let initConnection reach the sfu connect await
    await advanceTime(1); // flush the (already resolved) factory microtasks
    expect(state.connectionType).toBe(CONNECTION_TYPES.SERVER);
    await advanceTime(10000);
    expect(steps.logs).toInclude("sfu connection timeout");
    expect(state.connectionType).toBe(CONNECTION_TYPES.P2P);
    expect(state.fallbackMode).toBe(true);
    expect(transport.sfuClient).toBe(undefined);
});

test("hot-swap during an established call aborts the stale connection epoch", async () => {
    const sfuA = new MockSfuClient();
    const sfuB = new MockSfuClient();
    const firstLoad = new Deferred();
    const secondLoad = new Deferred();
    let loadCount = 0;
    const { transport, state } = makeTransport({
        loadSfuClient: () => (++loadCount === 1 ? firstLoad : secondLoad),
    });
    transport.serverInfo = SERVER_INFO;
    const firstRun = transport.initConnection({ sessionId: 1, channelId: 5 });
    // hot-swap arrives while the first SFU client is still loading
    transport.serverInfo = { ...SERVER_INFO, channelUUID: "other-uuid" };
    const secondRun = transport.initConnection({ sessionId: 1, channelId: 5 });
    secondLoad.resolve({ sfuClient: sfuB, SFU_CLIENT_STATE: MOCK_SFU_CLIENT_STATE });
    await secondRun;
    expect(transport.sfuClient).toBe(sfuB);
    // the stale run must dispose its client instead of clobbering the new one
    firstLoad.resolve({ sfuClient: sfuA, SFU_CLIENT_STATE: MOCK_SFU_CLIENT_STATE });
    await firstRun;
    expect(transport.sfuClient).toBe(sfuB);
    expect(transport.network.sfu).toBe(sfuB);
    expect(sfuA.calls.map(([name]) => name)).toEqual(["disconnect"]);
    expect(state.connectionType).toBe(CONNECTION_TYPES.SERVER);
});

test("SFU closed by the server: 'full' leaves the call, otherwise downgrade", async () => {
    const sfu = new MockSfuClient();
    const { transport, steps } = makeTransport({
        loadSfuClient: sfuFactory(sfu),
    });
    transport.serverInfo = SERVER_INFO;
    await transport.initConnection({ sessionId: 1, channelId: 5 });
    sfu.simulateConnected();
    sfu.simulateClose("full");
    expect(steps.leaveCall).toBe(1);
    // `_t` returns a lazy-translated string: compare the rendered text
    expect(String(steps.notifications.at(-1))).toBe("Channel full");

    // non-"full" close on a fresh transport: local downgrade to p2p
    const sfu2 = new MockSfuClient();
    const harness2 = makeTransport({ loadSfuClient: sfuFactory(sfu2) });
    harness2.transport.serverInfo = SERVER_INFO;
    await harness2.transport.initConnection({ sessionId: 1, channelId: 5 });
    sfu2.simulateConnected();
    sfu2.simulateClose();
    expect(harness2.steps.leaveCall).toBe(0);
    expect(harness2.state.connectionType).toBe(CONNECTION_TYPES.P2P);
    expect(harness2.state.fallbackMode).toBe(true);
});

test("dispose aborts in-flight connection attempts", async () => {
    const sfuA = new MockSfuClient();
    const load = new Deferred();
    const { transport, state } = makeTransport({ loadSfuClient: () => load });
    transport.serverInfo = SERVER_INFO;
    const run = transport.initConnection({ sessionId: 1, channelId: 5 });
    transport.dispose();
    load.resolve({ sfuClient: sfuA, SFU_CLIENT_STATE: MOCK_SFU_CLIENT_STATE });
    await run;
    expect(transport.sfuClient).toBe(undefined);
    expect(transport.network).toBe(undefined);
    expect(transport.serverInfo).toBe(undefined);
    expect(sfuA.calls.map(([name]) => name)).toEqual(["disconnect"]);
    expect(state.connectionType).toBe(undefined);
    expect(state.fallbackMode).toBe(false);
});
