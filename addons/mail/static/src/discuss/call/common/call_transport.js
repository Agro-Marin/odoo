/** @odoo-module native */
import { toRaw } from "@odoo/owl";
import { loadBundle } from "@web/core/assets";
import { browser } from "@web/core/browser/browser";
import { rpc } from "@web/core/network";
import { _t } from "@web/core/translation";
import { memoize } from "@web/core/utils/functions";
import { debounce } from "@web/core/utils/timing";

let sequence = 1;
export const getSequence = () => sequence++;

/** @typedef {'audio' | 'camera' | 'screen' } streamType */
export const CONNECTION_TYPES = { P2P: "p2p", SERVER: "server" };

/**
 * @return {Promise<{ SfuClient: import("@mail/../lib/odoo_sfu/odoo_sfu").SfuClient, SFU_CLIENT_STATE: import("@mail/../lib/odoo_sfu/odoo_sfu").SFU_CLIENT_STATE }>}
 */
const loadSfuAssets = memoize(async () => await loadBundle("mail.assets_odoo_sfu"));

/**
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
        /** @param {string} url */
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

export class Network {
    /** @type {import("@mail/discuss/call/common/peer_to_peer").PeerToPeer} */
    p2p;
    /** @type {import("@mail/../lib/odoo_sfu/odoo_sfu").SfuClient} */
    sfu;
    /** @type {Array<{ name: string, f: EventListener }>} */
    _listeners = [];
    /**
     * @param {import("@mail/discuss/call/common/peer_to_peer").PeerToPeer} p2p
     * @param {import("@mail/../lib/odoo_sfu/odoo_sfu").SfuClient} [sfu]
     */
    constructor(p2p, sfu) {
        this.p2p = p2p;
        this.sfu = sfu;
    }

    /**
     * @param {number} sessionId
     * @returns {Array<{type: string, state: string}>}
     */
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

    /** @param {import("@mail/../lib/odoo_sfu/odoo_sfu").SfuClient} sfu */
    addSfu(sfu) {
        if (this.sfu) {
            this.removeSfu();
        }
        this.sfu = sfu;
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
        this.sfu = undefined;
    }
    /**
     * @param {string} name
     * @param {function} f
     */
    addEventListener(name, f) {
        this._listeners.push({ name, f });
        this.p2p.addEventListener(name, f);
        this.sfu?.addEventListener(name, f);
    }
    /**
     * @param {streamType} type
     * @param {MediaStreamTrack | null} track
     */
    async updateUpload(type, track) {
        const proms = [this.p2p.updateUpload(type, track)];
        if (this.sfu?.state === "connected") {
            proms.push(this.sfu.updateUpload(type, track));
        }
        await Promise.all(proms);
    }
    /**
     * @param {number} sessionId
     * @param {Object<[streamType, boolean]>} states
     */
    updateDownload(sessionId, states) {
        this.p2p.updateDownload(sessionId, states);
        this.sfu?.updateDownload(sessionId, states);
    }
    /**
     * @param {import("#src/models/session.js").SessionInfo} info
     * @param {Object} [options]
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
 * @typedef {Object} ServerInfo
 * @property {string} url
 * @property {string} jsonWebToken
 * @property {string} channelUUID
 */

/**
 * @typedef {Object} CallTransportHooks
 * @property {() => Array<RTCIceServer>} getIceServers
 * @property {() => Object} getFreshInfo
 * @property {() => number[]} getPeerSessionIds
 * @property {(state: string) => void} setLocalConnectionState
 * @property {() => void} updateUpload
 * @property {(event: CustomEvent) => void} onNetworkUpdate
 * @property {(event: CustomEvent) => void} onNetworkLog
 * @property {(entry: string, options?: Object) => void} log
 * @property {(text: string) => void} notify
 * @property {() => void} leaveCall
 */
export class CallTransport {
    /** @type {Network|undefined} */
    network;
    /** @type {import("@mail/../lib/odoo_sfu/odoo_sfu").SfuClient|undefined} */
    sfuClient;
    /** @type {import("@mail/../lib/odoo_sfu/odoo_sfu").SFU_CLIENT_STATE|undefined} */
    SFU_CLIENT_STATE;
    /** @type {ServerInfo|undefined} */
    serverInfo;
    /** @type {number} */
    sfuTimeout;
    /** @type {number} */
    _connectEpoch = 0;
    /** @type {number} */
    _p2pRecoveryCount = 0;

    /**
     * @param {Object} param0
     * @param {() => import("@mail/discuss/call/common/peer_to_peer").PeerToPeer} param0.getP2p
     * @param {import("@mail/discuss/call/common/rtc_service").RtcCallState} param0.state
     * @param {CallTransportHooks} param0.hooks
     * @param {typeof loadSfuClient} [param0.loadSfuClient]
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
     * @param {Object} param0
     * @param {number} param0.sessionId
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
     * @param {Object} [param0={}]
     * @param {boolean} [param0.asFallback=false]
     * @return {Promise<void>}
     */
    async call({ asFallback = false } = {}) {
        if (asFallback && !this.state.fallbackMode) {
            return;
        }
        if (this.state.connectionType === CONNECTION_TYPES.SERVER) {
            if (this.sfuClient.state === this.SFU_CLIENT_STATE.DISCONNECTED) {
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

    async downgrade() {
        if (this.state.connectionType !== CONNECTION_TYPES.SERVER) {
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

    /** @param {boolean} hasTurnServer */
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

    /** @param {CustomEvent<{state: string, cause?: string}>} ev */
    async _handleSfuStateChange({ detail: { state, cause } }) {
        this.hooks.log(`connection state change: ${state}`, { state, cause });
        this.hooks.setLocalConnectionState(state);
        switch (state) {
            case this.SFU_CLIENT_STATE.AUTHENTICATED:
                this.p2p.removeALlPeers();
                this.sfuClient.broadcast({ sequence: getSequence() });
                break;
            case this.SFU_CLIENT_STATE.CONNECTED:
                browser.clearTimeout(this.sfuTimeout);
                this.sfuClient.updateInfo(this.hooks.getFreshInfo(), {
                    needRefresh: true,
                });
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

    disconnect() {
        this.network?.disconnect();
    }

    dispose() {
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
