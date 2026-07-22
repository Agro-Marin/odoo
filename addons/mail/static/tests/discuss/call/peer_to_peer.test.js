import {
    defineMailModels,
    mockGetMedia,
    onlineTest,
} from "@mail/../tests/mail_test_helpers";
import {
    MAX_NOTIFICATION_RETRIES,
    PeerToPeer,
    STREAM_TYPE,
    UPDATE_EVENT,
} from "@mail/discuss/call/common/peer_to_peer";
import { describe, expect, test } from "@odoo/hoot";
import { advanceTime } from "@odoo/hoot-mock";
import {
    asyncStep,
    makeServerError,
    mountWebClient,
    onRpc,
    waitForSteps,
} from "@web/../tests/web_test_helpers";
import { browser } from "@web/core/browser/browser";

describe.current.tags("desktop");
defineMailModels();

class Network {
    _peerToPeerInstances = new Map();
    _notificationRoute;
    constructor(route) {
        this._notificationRoute = route || "/any/mock/notification";
        onRpc(this._notificationRoute, async (req) => {
            const {
                params: { peer_notifications },
            } = await req.json();
            for (const notification of peer_notifications) {
                const [sender_session_id, target_session_ids, content] = notification;
                for (const id of target_session_ids) {
                    const p2p = this._peerToPeerInstances.get(id);
                    p2p.handleNotification(sender_session_id, content);
                }
            }
        });
    }
    /**
     * @param id
     * @return {{id, p2p: PeerToPeer}}
     */
    register(id) {
        const p2p = new PeerToPeer({ notificationRoute: this._notificationRoute });
        this._peerToPeerInstances.set(id, p2p);
        return { id, p2p };
    }
    close() {
        for (const p2p of this._peerToPeerInstances.values()) {
            p2p.disconnect();
        }
    }
}

onlineTest("basic peer to peer connection", async () => {
    await mountWebClient();
    const channelId = 1;
    const network = new Network();
    const user1 = network.register(1);
    const user2 = network.register(2);
    user2.p2p.addEventListener("update", ({ detail: { name, payload } }) => {
        if (name === UPDATE_EVENT.CONNECTION_CHANGE && payload.state === "connected") {
            asyncStep(payload.state);
        }
    });

    user2.p2p.connect(user2.id, channelId);
    user1.p2p.connect(user1.id, channelId);
    await user1.p2p.addPeer(user2.id);
    await waitForSteps(["connected"]);
    network.close();
});

onlineTest("mesh peer to peer connections", async () => {
    await mountWebClient();
    const channelId = 2;
    const network = new Network();
    const userCount = 10;
    const users = Array.from({ length: userCount }, (_, i) => network.register(i));
    const promises = [];
    for (const user of users) {
        user.p2p.connect(user.id, channelId);
        for (let i = 0; i < user.id; i++) {
            promises.push(user.p2p.addPeer(i));
        }
    }
    await Promise.all(promises);

    let connectionsCount = 0;
    for (const user of users) {
        connectionsCount += user.p2p.peers.size;
    }
    expect(connectionsCount).toBe(userCount * (userCount - 1));
    connectionsCount = 0;
    network.close();
    for (const user of users) {
        connectionsCount += user.p2p.peers.size;
    }
    expect(connectionsCount).toBe(0);
});

onlineTest("connection recovery", async () => {
    await mountWebClient();
    const channelId = 1;
    const network = new Network();
    const user1 = network.register(1);
    const user2 = network.register(2);
    user2.remoteStates = new Map();
    user2.p2p.addEventListener("update", ({ detail: { name, payload } }) => {
        if (name === UPDATE_EVENT.CONNECTION_CHANGE && payload.state === "connected") {
            asyncStep(payload.state);
        }
    });

    user1.p2p.connect(user1.id, channelId);
    user1.p2p.addPeer(user2.id);
    // only connecting user2 after user1 has called addPeer so that user2 ignores notifications
    // from user1, which simulates a connection drop that should be recovered.
    user2.p2p.connect(user2.id, channelId);
    const openPromise = new Promise((resolve) => {
        user1.p2p.peers.get(2).dataChannel.onopen = resolve;
    });
    advanceTime(5_000); // recovery timeout
    await openPromise;
    await waitForSteps(["connected"]);
    network.close();
});

onlineTest("can broadcast a stream and control download", async () => {
    mockGetMedia();
    await mountWebClient();
    const channelId = 3;
    const network = new Network();
    const user1 = network.register(1);
    const user2 = network.register(2);
    user2.remoteMedia = new Map();
    const trackPromise = new Promise((resolve) => {
        user2.p2p.addEventListener("update", ({ detail: { name, payload } }) => {
            if (name === UPDATE_EVENT.TRACK) {
                user2.remoteMedia.set(payload.sessionId, {
                    [payload.type]: {
                        track: payload.track,
                        active: payload.active,
                    },
                });
                resolve();
            }
        });
    });

    user2.p2p.connect(user2.id, channelId);
    user1.p2p.connect(user1.id, channelId);
    await user1.p2p.addPeer(user2.id);
    const videoStream = await browser.navigator.mediaDevices.getUserMedia({
        video: true,
    });
    const videoTrack = videoStream.getVideoTracks()[0];
    await user1.p2p.updateUpload(STREAM_TYPE.CAMERA, videoTrack);
    await trackPromise;
    const user2RemoteMedia = user2.remoteMedia.get(user1.id);
    const user2CameraTransceiver = user2.p2p.peers
        .get(user1.id)
        .getTransceiver(STREAM_TYPE.CAMERA);
    expect(user2CameraTransceiver.direction).toBe("recvonly");
    expect(user2RemoteMedia[STREAM_TYPE.CAMERA].track.kind).toBe("video");
    expect(user2RemoteMedia[STREAM_TYPE.CAMERA].active).toBe(true);
    user2.p2p.updateDownload(user1.id, { camera: false });
    expect(user2CameraTransceiver.direction).toBe("inactive");
    network.close();
});

onlineTest("can broadcast arbitrary messages (dataChannel)", async () => {
    await mountWebClient();
    const channelId = 4;
    const network = new Network();
    const user1 = network.register(1);
    const user2 = network.register(2);
    user2.p2p.connect(user2.id, channelId);
    user1.p2p.connect(user1.id, channelId);
    await user1.p2p.addPeer(user2.id);
    user1.inbox = [];
    const pongPromise = new Promise((resolve) => {
        user1.p2p.addEventListener("update", ({ detail: { name, payload } }) => {
            if (name === UPDATE_EVENT.BROADCAST) {
                user1.inbox.push(payload);
                resolve();
            }
        });
    });
    user2.inbox = [];
    user2.p2p.addEventListener("update", ({ detail: { name, payload } }) => {
        if (name === UPDATE_EVENT.BROADCAST && payload.message === "ping") {
            user2.inbox.push(payload);
            user2.p2p.broadcast("pong");
        }
    });
    user1.p2p.broadcast("ping");
    await pongPromise;
    expect(user2.inbox[0].senderId).toBe(user1.id);
    expect(user2.inbox[0].message).toBe("ping");
    expect(user1.inbox[0].senderId).toBe(user2.id);
    expect(user1.inbox[0].message).toBe("pong");
    network.close();
});

test("failed notification batches retry with backoff then give up", async () => {
    await mountWebClient();
    const route = "/failing/mock/notification";
    let rpcCount = 0;
    onRpc(route, () => {
        rpcCount++;
        throw makeServerError({ message: "offline" });
    });
    const p2p = new PeerToPeer({ notificationRoute: route });
    p2p.connect(1, 1);
    const notifyProm = p2p._busNotify("disconnect", { targets: [2] });
    // Let the batch delay and every backoff delay (each bounded by
    // MAXIMUM_RECONNECT_DELAY) elapse. Advance in chunks, because a timer the
    // async retry loop schedules *during* an advance is only picked up by the
    // next one -- so the number of chunks needed is the number of sequential
    // timers, not the total virtual time. Stop as soon as the retries are
    // exhausted instead of running a fixed count: the backoff is derived from
    // INITIAL_RECONNECT_DELAY, which is randomised at module load, so any fixed
    // budget sitting near the boundary fails on some page loads and not others.
    for (let i = 0; i < 40 && rpcCount < 1 + MAX_NOTIFICATION_RETRIES; i++) {
        await advanceTime(10_000);
    }
    // initial attempt + capped retries, no infinite ~100ms-cadence recursion
    expect(rpcCount).toBe(1 + MAX_NOTIFICATION_RETRIES);
    // the undeliverable batch is dropped
    expect(p2p._notificationsToSend.size).toBe(0);
    // resolves cleanly: failures must not leak rejections to the callers
    await notifyProm;
    await advanceTime(60_000);
    expect(rpcCount).toBe(1 + MAX_NOTIFICATION_RETRIES);
    p2p.disconnect();
});

test("an offer queued while the notification RPC is in flight is not dropped", async () => {
    await mountWebClient();
    const route = "/inflight/mock/notification";
    /** @type {any[][]} content batches, one per RPC call */
    const batches = [];
    let markFirstStarted;
    const firstStarted = new Promise((resolve) => (markFirstStarted = resolve));
    let releaseFirst;
    const firstReleased = new Promise((resolve) => (releaseFirst = resolve));
    let rpcCount = 0;
    onRpc(route, async (req) => {
        const {
            params: { peer_notifications },
        } = await req.json();
        batches.push(peer_notifications);
        if (++rpcCount === 1) {
            // hold the first batch in flight so a newer offer can be queued
            // for the same target before the post-RPC cleanup runs
            markFirstStarted();
            await firstReleased;
        }
    });
    const p2p = new PeerToPeer({ notificationRoute: route });
    p2p.connect(1, 1);

    // queue OFFER v1 to peer 2 (fire and forget: the returned promise only
    // settles once the whole queue drains)
    p2p._busNotify("offer", { targets: [2], payload: { sdp: "v1" } });
    // let the batch delay elapse so the first RPC is dispatched
    await advanceTime(10_000);
    await firstStarted;

    // While RPC #1 is in flight, queue a NEWER offer for the same target. It
    // reuses the `latestOffer_to:2` key, overwriting the map entry that RPC #1
    // is about to acknowledge.
    p2p._busNotify("offer", { targets: [2], payload: { sdp: "v2" } });

    // Release RPC #1: its post-RPC cleanup must delete the entry ONLY if it is
    // still the one it sent — the superseded v2 must survive and be sent next.
    releaseFirst();
    for (let i = 0; i < 3; i++) {
        await advanceTime(10_000);
    }

    // Regression: v2 used to be deleted (by key) right after RPC #1 and never
    // sent, stalling the handshake. It must now go out in a second batch.
    expect(rpcCount).toBe(2);
    expect(batches[0][0][2]).toInclude("v1");
    expect(batches[1][0][2]).toInclude("v2");
    expect(p2p._notificationsToSend.size).toBe(0);
    p2p.disconnect();
});

onlineTest("recovery timeout firing after peer removal is a no-op", async () => {
    await mountWebClient();
    const network = new Network();
    const user1 = network.register(1);
    // registered so the mock route can deliver notifications, but never
    // connected: peer 2 ignores them and never answers.
    network.register(2);
    user1.p2p.connect(user1.id, 1);
    // schedule a recovery for the unanswering peer, then simulate the stale
    // race where the peer vanishes without its recovery timeout being
    // cleared.
    user1.p2p.addPeer(2);
    user1.p2p._recover(2, "test: forced recovery");
    expect(user1.p2p._recoverTimeouts.size).toBe(1);
    user1.p2p.peers.get(2).disconnect();
    user1.p2p.peers.delete(2);
    await advanceTime(60_000);
    // the recovery callback must bail out (it previously read
    // `peer.connection.connectionState` before its null guard)
    expect(user1.p2p._recoverTimeouts.size).toBe(0);
    expect(user1.p2p.peers.size).toBe(0);
    network.close();
});

onlineTest("can reject arbitrary offers", async () => {
    await mountWebClient();
    const channelId = 1;
    const network = new Network();
    const user1 = network.register(1);
    const user2 = network.register(2);
    user2.p2p.connect(user2.id, channelId);
    user1.p2p.connect(user1.id, channelId);
    user2.p2p._emitLog = (id, message) => {
        if (message === "offer rejected") {
            asyncStep("offer rejected");
        }
    };
    user2.p2p.acceptOffer = (id, sequence) => id !== user1.id || sequence > 20;
    user1.p2p.addPeer(user2.id, { sequence: 19 });
    await waitForSteps(["offer rejected"]);
    network.close();
});
