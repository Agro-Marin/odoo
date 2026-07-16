/** @odoo-module native */
import { toRaw } from "@odoo/owl";
import { loadBundle } from "@web/core/assets";
import { browser } from "@web/core/browser/browser";
import { _t } from "@web/core/l10n/translation";
import { rpc } from "@web/core/network/rpc";
import { memoize } from "@web/core/utils/functions";
import { debounce } from "@web/core/utils/timing";

let sequence = 1;
export const getSequence = () => sequence++;

/**
 * @typedef {'audio' | 'camera' | 'screen' } streamType
 */

export const CONNECTION_TYPES = { P2P: "p2p", SERVER: "server" };

/**
 * @return {Promise<{ SfuClient: import("@mail/../lib/odoo_sfu/odoo_sfu").SfuClient, SFU_CLIENT_STATE: import("@mail/../lib/odoo_sfu/odoo_sfu").SFU_CLIENT_STATE }>}
 */
const loadSfuAssets = memoize(async () => await loadBundle("mail.assets_odoo_sfu"));

/**
 * Default SfuClient factory: loads the (lazy) SFU asset bundle and returns a
 * fresh client together with the state enum of the loaded module. Injectable
 * on `CallTransport` so tests can substitute a mock client without the
 * network/bundle round trip.
 *
 * The caller is responsible for the returned client (assigning it to
 * `transport.sfuClient` after checking it is still the latest connection
 * attempt, disconnecting it otherwise).
 *
 * @returns {Promise<{ sfuClient: import("@mail/../lib/odoo_sfu/odoo_sfu").SfuClient, SFU_CLIENT_STATE: Object }>}
 */
export async function loadSfuClient() {
    const load = async () => {
        await loadSfuAssets();
        const sfuModule = await import("@mail/../lib/odoo_sfu/odoo_sfu");
        return {
            sfuClient: new sfuModule.SfuClient(),
            SFU_CLIENT_STATE: sfuModule.SFU_CLIENT_STATE,
        };
    };
    try {
        return await load();
    } catch {
        // trying again with a delay in case of race condition with the asset loading.
        return new Promise((resolve, reject) => {
            browser.setTimeout(async () => {
                try {
                    resolve(await load());
                } catch (error) {
                    reject(error);
                }
            }, 1000);
        });
    }
}

/**
 * @param {Array<RTCIceServer>} iceServers
 * @returns {Boolean}
 */
export function hasTurn(iceServers) {
    return iceServers.some((server) => {
        const isTurnUrl = (url) => /^turns?:/.test(url);
        let hasTurn = false;
        if (server.url) {
            hasTurn = isTurnUrl(server.url);
        }
        if (server.urls) {
            if (Array.isArray(server.urls)) {
                hasTurn = server.urls.some(isTurnUrl) || hasTurn;
            } else {
                hasTurn = isTurnUrl(server.urls) || hasTurn;
            }
        }
        return hasTurn;
    });
}

/**
 * Allows to use both peer to peer and SFU connections simultaneously, which makes it possible to
 * establish a connection with other call participants with the SFU when possible, and still handle
 * peer-to-peer for the participants who did not manage to establish a SFU connection.
 */
export class Network {
    /** @type {import("@mail/discuss/call/common/peer_to_peer").PeerToPeer} */
    p2p;
    /** @type {import("@mail/../lib/odoo_sfu/odoo_sfu").SfuClient} */
    sfu;
    /** @type {[{ name: string, f: EventListener }]} */
    _listeners = [];
    /**
     * @param {import("@mail/discuss/call/common/peer_to_peer").PeerToPeer} p2p
     * @param {import("@mail/../lib/odoo_sfu/odoo_sfu").SfuClient} [sfu]
     */
    constructor(p2p, sfu) {
        this.p2p = p2p;
        this.sfu = sfu;
    }

    getSfuConsumerStats(sessionId) {
        const consumers = this.sfu?._consumers.get(sessionId);
        if (!consumers) {
            return [];
        }
        return Object.entries(consumers).map(([type, consumer]) => {
            let state = "active";
            if (!consumer) {
                state = "no consumer";
            } else if (consumer.closed) {
                state = "closed";
            } else if (consumer.paused) {
                state = "paused";
            } else if (!consumer.track) {
                state = "no track";
            } else if (!consumer.track.enabled) {
                state = "track disabled";
            } else if (consumer.track.muted) {
                state = "track muted";
            }
            return { type, state };
        });
    }

    /**
     * add a SFU to the network.
     * @param {import("@mail/../lib/odoo_sfu/odoo_sfu").SfuClient} sfu
     */
    addSfu(sfu) {
        if (this.sfu) {
            this.removeSfu();
        }
        this.sfu = sfu;
        // listeners registered before the SFU existed (p2p listeners are
        // attached at network creation, the SFU bundle loads seconds later)
        // must reach the SFU too
        for (const { name, f } of this._listeners) {
            sfu.addEventListener(name, f);
        }
    }
    removeSfu() {
        if (!this.sfu) {
            return;
        }
        for (const { name, f } of this._listeners) {
            this.sfu.removeEventListener(name, f);
        }
        this.sfu.disconnect();
        // full teardown: a kept reference would still show up in stats, be
        // disconnected again and accumulate listeners on the next `addSfu`.
        this.sfu = undefined;
    }
    /**
     * @param {string} name
     * @param {function} f
     * @override
     */
    addEventListener(name, f) {
        this._listeners.push({ name, f });
        this.p2p.addEventListener(name, f);
        this.sfu?.addEventListener(name, f);
    }
    /**
     * @param {streamType} type
     * @param {MediaStreamTrack | null} track track to be sent to the other call participants,
     * not setting it will remove the track from the server
     */
    async updateUpload(type, track) {
        const proms = [this.p2p.updateUpload(type, track)];
        if (this.sfu?.state === "connected") {
            proms.push(this.sfu.updateUpload(type, track));
        }
        await Promise.all(proms);
    }
    /**
     * Stop or resume the consumption of tracks from the other call participants.
     *
     * @param {number} sessionId
     * @param {Object<[streamType, boolean]>} states e.g: { audio: true, camera: false }
     */
    updateDownload(sessionId, states) {
        this.p2p.updateDownload(sessionId, states);
        this.sfu?.updateDownload(sessionId, states);
    }
    /**
     * Updates the server with the info of the session (isTalking, isCameraOn,...) so that it can broadcast it to the
     * other call participants.
     *
     * @param {import("#src/models/session.js").SessionInfo} info
     * @param {Object} [options] see documentation of respective classes
     */
    updateInfo(info, options = {}) {
        this.p2p.updateInfo(info, options);
        this.sfu?.updateInfo(info, options);
    }
    disconnect() {
        for (const { name, f } of this._listeners.splice(0)) {
            this.p2p.removeEventListener(name, f);
            this.sfu?.removeEventListener(name, f);
        }
        this.p2p.disconnect();
        this.sfu?.disconnect();
    }
}

/**
 * Delegate surface the coordinator (Rtc) provides to the transport. Every
 * UI/store concern goes through these callbacks so the transport state
 * machine stays headless-testable.
 *
 * @typedef {Object} CallTransportHooks
 * @property {() => Array<RTCIceServer>} getIceServers
 * @property {() => Object} getFreshInfo session info with the video flags
 *  realigned to the actual local tracks (advertised over a fresh transport)
 * @property {() => number[]} getPeerSessionIds ids of the remote rtc sessions
 *  of the current call channel (excluding the local session)
 * @property {(state: string) => void} setLocalConnectionState
 * @property {() => void} updateUpload fan out all local tracks (audio,
 *  camera, screen) through the network
 * @property {(event: CustomEvent) => void} onNetworkUpdate "update" listener
 * @property {(event: CustomEvent) => void} onNetworkLog "log" listener
 * @property {(entry: string, options?: Object) => void} log logs against the
 *  local session
 * @property {(text: string) => void} notify warning notification
 * @property {() => void} leaveCall used when the SFU closes with "full"
 */

/**
 * Owns the network lifecycle of a call: p2p vs SFU selection, the SfuClient
 * connect/downgrade/hot-swap state machine, the connect-epoch logic and the
 * p2p offer sequence numbers. Holds no OWL/store state of its own beyond the
 * shared reactive `state` slots it is given (`connectionType`,
 * `fallbackMode`, `channel`).
 */
export class CallTransport {
    /** @type {Network|undefined} per-call composite network */
    network;
    /** @type {import("@mail/../lib/odoo_sfu/odoo_sfu").SfuClient|undefined} */
    sfuClient;
    /** State enum of the loaded SFU module (set by the client factory). */
    SFU_CLIENT_STATE;
    /** Server info of the SFU attributed to the current call, if any. */
    serverInfo;
    /** @type {number} watchdog for the whole SFU connection sequence */
    sfuTimeout;
    /**
     * Generation token for `initConnection`: bumped at each new connection
     * attempt (and on `dispose()`) so a stale run aborts after each await
     * instead of clobbering the state of a newer one.
     * @type {number}
     */
    _connectEpoch = 0;
    /** @type {number} count of how many times the p2p service attempted a connection recovery */
    _p2pRecoveryCount = 0;

    /**
     * @param {Object} param0
     * @param {() => import("@mail/discuss/call/common/peer_to_peer").PeerToPeer} param0.getP2p
     *  accessor (the p2p service is assigned to the coordinator after setup)
     * @param {Object} param0.state shared reactive call state; the transport
     *  reads `channel` and owns `connectionType` / `fallbackMode`
     * @param {CallTransportHooks} param0.hooks
     * @param {typeof loadSfuClient} [param0.loadSfuClient] injectable
     *  SfuClient factory
     */
    constructor({ getP2p, state, hooks, loadSfuClient: loadSfuClientFn }) {
        this._getP2p = getP2p;
        this.state = state;
        this.hooks = hooks;
        this._loadSfuClient = loadSfuClientFn ?? loadSfuClient;
        this._handleSfuStateChange = this._handleSfuStateChange.bind(this);
        this.upgradeConnectionDebounce = debounce(
            () => {
                this._upgradeConnection();
            },
            15000,
            { leading: true, trailing: false },
        );
    }

    /** @returns {import("@mail/discuss/call/common/peer_to_peer").PeerToPeer} */
    get p2p() {
        return this._getP2p();
    }

    /**
     * (Re)establishes the network of the call: always connects p2p (we may
     * need to receive peer-to-peer connections from users who failed to
     * connect to the SFU), and adds a SFU client when `serverInfo` is set.
     *
     * Reentrancy guard (`joinCall` racing an `sfu_hot_swap`, or the call
     * ending during the multi-second SFU load): a run that is no longer
     * the latest aborts after each await, so handlers are never
     * registered twice and a fresh SfuClient cannot clobber a newer one.
     *
     * @param {Object} param0
     * @param {number} param0.sessionId id of the local rtc session
     * @param {number} param0.channelId
     */
    async initConnection({ sessionId, channelId }) {
        const epoch = ++this._connectEpoch;
        this.hooks.setLocalConnectionState("selecting network type");
        this.state.connectionType = CONNECTION_TYPES.P2P;
        this.network?.disconnect();
        const info = this.hooks.getFreshInfo();
        this.p2p.connect(sessionId, channelId, {
            info,
            iceServers: this.hooks.getIceServers(),
        });
        this.network = new Network(this.p2p);
        // register BEFORE any await: a p2p-fallback participant can react to
        // our session insert immediately and complete its handshake while the
        // SFU bundle is still loading — TRACK/BROADCAST events emitted with no
        // listener are dropped for good (the connection is healthy, so no
        // recovery path ever replays them). addSfu() forwards these listeners
        // to the SFU client once it is ready.
        this.network.addEventListener("stateChange", this._handleSfuStateChange);
        this.network.addEventListener("update", this.hooks.onNetworkUpdate);
        this.network.addEventListener("log", this.hooks.onNetworkLog);
        this.hooks.updateUpload();
        if (this.serverInfo) {
            this.hooks.log("loading sfu server", {
                step: "loading sfu server",
                serverInfo: toRaw(this.serverInfo),
            });
            this.hooks.setLocalConnectionState("loading SFU assets");
            try {
                const { sfuClient, SFU_CLIENT_STATE } = await this._loadSfuClient();
                if (epoch !== this._connectEpoch) {
                    // a newer connection attempt (or the end of the call)
                    // superseded this run.
                    sfuClient.disconnect();
                    return;
                }
                this.SFU_CLIENT_STATE = SFU_CLIENT_STATE;
                this.sfuClient?.disconnect();
                this.sfuClient = sfuClient;
                this.state.connectionType = CONNECTION_TYPES.SERVER;
                this.network.addSfu(this.sfuClient);
            } catch (e) {
                if (epoch !== this._connectEpoch) {
                    return;
                }
                this.state.fallbackMode = true;
                this.hooks.notify(
                    _t("Failed to load the SFU server, falling back to peer-to-peer"),
                );
                this.hooks.log("failed to load sfu server", {
                    error: e,
                    important: true,
                });
            }
            this.hooks.setLocalConnectionState("initializing");
        } else {
            this.hooks.log("no sfu server info, using peer-to-peer");
        }
        if (this.state.channel) {
            await this.call();
            if (epoch !== this._connectEpoch) {
                return;
            }
            this.hooks.updateUpload();
        }
    }

    /**
     * Connects to the other call participants through the current connection
     * type: SFU handshake when on server mode, p2p offers otherwise.
     *
     * @param {Object} [param0={}]
     * @param {boolean} [param0.asFallback=false] whether the call is made as a fallback to the SFU, in which case
     * p2p connections are offered more eagerly as other participants may not offer them if their primary connection
     * type is SFU.
     * @return {Promise<void>}
     */
    async call({ asFallback = false } = {}) {
        if (asFallback && !this.state.fallbackMode) {
            return;
        }
        if (this.state.connectionType === CONNECTION_TYPES.SERVER) {
            if (this.sfuClient.state === this.SFU_CLIENT_STATE.DISCONNECTED) {
                // Watchdog for the whole connection sequence: `connect()`
                // resolves at AUTHENTICATED, before the transports are ready,
                // so the timeout must stay armed until the CONNECTED state
                // change (which clears it), or until `downgrade`.
                browser.clearTimeout(this.sfuTimeout);
                this.sfuTimeout = browser.setTimeout(() => {
                    this.hooks.log("sfu connection timeout", {
                        important: true,
                    });
                    this.downgrade();
                }, 10000);
                try {
                    await this.sfuClient.connect(
                        this.serverInfo.url,
                        this.serverInfo.jsonWebToken,
                        {
                            channelUUID: this.serverInfo.channelUUID,
                            iceServers: this.hooks.getIceServers(),
                        },
                    );
                } catch (error) {
                    // single failure funnel with the timeout above: fall back
                    // to p2p locally instead of letting the rejection abort
                    // the caller (e.g. the rest of the `joinCall` setup).
                    this.hooks.log("failed to connect to the SFU server", {
                        error,
                        important: true,
                    });
                    await this.downgrade();
                }
            }
            return;
        }
        const peerSessionIds = this.hooks.getPeerSessionIds();
        if (peerSessionIds.length === 0) {
            return;
        }
        const sequence = getSequence();
        for (const id of peerSessionIds) {
            this.p2p.addPeer(id, { sequence });
        }
    }

    /**
     * Falls the call back to peer-to-peer, dropping the SFU client.
     */
    async downgrade() {
        if (this.state.connectionType !== CONNECTION_TYPES.SERVER) {
            // already downgraded: the 10s connection timeout and a
            // `connect()` rejection can both fire for the same failure, keep
            // a single funnel.
            return;
        }
        browser.clearTimeout(this.sfuTimeout);
        this.serverInfo = undefined;
        this.state.fallbackMode = true;
        this.state.connectionType = CONNECTION_TYPES.P2P;
        this.network?.removeSfu();
        this.sfuClient = undefined;
        await this.call();
        this.hooks.updateUpload();
    }

    /**
     * Called when the p2p service attempted a connection recovery while on a
     * pure p2p call: past the first attempt (or right away without a TURN
     * server) we ask the server for a SFU upgrade.
     *
     * @param {boolean} hasTurnServer
     */
    onP2pRecovery(hasTurnServer) {
        this._p2pRecoveryCount++;
        if (this._p2pRecoveryCount > 1 || !hasTurnServer) {
            this.upgradeConnectionDebounce();
        }
    }

    async _upgradeConnection() {
        const channelId = this.state.channel?.id;
        if (this.serverInfo || this.state.fallbackMode || !channelId) {
            return;
        }
        await rpc(
            "/mail/rtc/channel/upgrade_connection",
            { channel_id: channelId },
            { silent: true },
        );
    }

    async _handleSfuStateChange({ detail: { state, cause } }) {
        this.hooks.log(`connection state change: ${state}`, { state, cause });
        this.hooks.setLocalConnectionState(state);
        switch (state) {
            case this.SFU_CLIENT_STATE.AUTHENTICATED:
                // if we are hot-swapping connection type, we clear the p2p as late as possible
                this.p2p.removeALlPeers();
                this.sfuClient.broadcast({ sequence: getSequence() });
                break;
            case this.SFU_CLIENT_STATE.CONNECTED:
                browser.clearTimeout(this.sfuTimeout);
                this.sfuClient.updateInfo(this.hooks.getFreshInfo(), {
                    needRefresh: true, // asks the server to send the info from all the channel
                });
                // fan out through the Network so p2p and SFU stay consistent
                this.hooks.updateUpload();
                return;
            case this.SFU_CLIENT_STATE.CLOSED:
                {
                    if (!this.state.channel) {
                        return;
                    }
                    let text;
                    if (cause === "full") {
                        text = _t("Channel full");
                        this.hooks.leaveCall();
                    } else {
                        text = _t(
                            "Connection to SFU server closed by the server, falling back to peer-to-peer",
                        );
                        this.hooks.log(text, { important: true });
                        this.downgrade();
                    }
                    this.hooks.notify(text);
                }
                return;
        }
    }

    /**
     * Disconnects the whole network (p2p and SFU) without resetting the
     * per-call state; part of the end-of-call sequence, before `dispose()`.
     */
    disconnect() {
        this.network?.disconnect();
    }

    /**
     * Resets the per-call transport state. Does not disconnect the network:
     * the end-of-call path (`endCall`) disconnects explicitly before the
     * cleanup, while cross-tab remotes never had a network to disconnect.
     */
    dispose() {
        // abort any in-flight `initConnection` run
        this._connectEpoch++;
        browser.clearTimeout(this.sfuTimeout);
        this.sfuClient = undefined;
        this.network = undefined;
        this.serverInfo = undefined;
        this._p2pRecoveryCount = 0;
        this.state.connectionType = undefined;
        this.state.fallbackMode = false;
    }
}
