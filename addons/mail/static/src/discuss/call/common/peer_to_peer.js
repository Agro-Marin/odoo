/** @odoo-module native */
import { browser } from "@web/core/browser/browser";
import { rpc } from "@web/core/network";
import { Deferred } from "@web/core/utils/concurrency";
export const STREAM_TYPE = Object.freeze({
    AUDIO: "audio",
    CAMERA: "camera",
    SCREEN: "screen",
});
export const UPDATE_EVENT = Object.freeze({
    BROADCAST: "broadcast",
    CONNECTION_CHANGE: "connection_change",
    DISCONNECT: "disconnect",
    INFO_CHANGE: "info_change",
    RECOVERY: "recovery",
    TRACK: "track",
});
const LOG_LEVEL = Object.freeze({
    NONE: "none",
    DEBUG: "debug",
    INFO: "info",
    WARN: "warn",
    ERROR: "error",
});
const INTERNAL_EVENT = Object.freeze({
    ANSWER: "answer",
    BROADCAST: "broadcast",
    DISCONNECT: "disconnect",
    ICE_CANDIDATE: "ice-candidate",
    INFO: "info",
    OFFER: "offer",
    TRACK_CHANGE: "trackChange",
});
const ORDERED_TRANSCEIVER_TYPES = [
    STREAM_TYPE.AUDIO,
    STREAM_TYPE.CAMERA,
    STREAM_TYPE.SCREEN,
];
const DEFAULT_BUS_BATCH_DELAY = 100;
const INITIAL_RECONNECT_DELAY = 2_000 + Math.random() * 1_000;
const MAXIMUM_RECONNECT_DELAY = 25_000 + Math.random() * 5_000;
export const MAX_NOTIFICATION_RETRIES = 5;
/** @type {Set<RTCIceConnectionState>} */
const INVALID_ICE_CONNECTION_STATES = new Set(["disconnected", "failed", "closed"]);
const IS_CLIENT_RTC_COMPATIBLE = Boolean(
    window.RTCPeerConnection && window.MediaStream,
);
const DEFAULT_ICE_SERVERS = [
    { urls: ["stun:stun1.l.google.com:19302", "stun:stun2.l.google.com:19302"] },
];
const DEFAULT_NOTIFICATION_ROUTE = "/mail/rtc/session/notify_call_members";

/**
 * @typedef {Object} Media
 * @property {MediaStreamTrack | null} track
 * @property {boolean} active
 * @property {boolean} accepted
 */
/**
 * @typedef {Object} Info
 * @property {boolean} isSelfMuted
 * @property {boolean} isRaisingHand
 * @property {boolean} isDeaf
 * @property {boolean} isTalking
 * @property {boolean} isCameraOn
 * @property {boolean} isScreenSharingOn
 */
/**
 * @typedef {Object} QueuedNotification
 * @property {number} sender
 * @property {number[]} targets
 * @property {INTERNAL_EVENT[keyof INTERNAL_EVENT]} event
 * @property {number} channelId
 * @property {NotificationPayload} payload
 */
/**
 * @typedef {Object} NotificationPayload
 * @property {RTCSessionDescriptionInit} [sdp]
 * @property {RTCIceCandidateInit} [candidate]
 * @property {number} [sequence]
 * @property {boolean} [isTalking]
 * @property {boolean} [isCameraOn]
 * @property {boolean} [isScreenSharingOn]
 * @property {boolean} [isSelfMuted]
 * @property {boolean} [isRaisingHand]
 * @property {boolean} [isDeaf]
 */
/**
 * @typedef {Object} FormattedPeerStats
 * @property {RTCPeerConnectionState} [connectionState]
 * @property {RTCIceConnectionState} [iceConnectionState]
 * @property {RTCIceGatheringState} [iceGatheringState]
 * @property {RTCIceCandidateType | ""} [localCandidateType]
 * @property {RTCIceCandidateType | ""} [remoteCandidateType]
 * @property {RTCDataChannelState} [dataChannelState]
 * @property {RTCDtlsTransportState} [dtlsState]
 * @property {RTCIceTransportState} [iceState]
 * @property {number} [packetsReceived]
 * @property {number} [packetsSent]
 */
export class Peer {
    /** @type {number} */
    id;
    /** @type {RTCPeerConnection} */
    connection;
    /** @type {number} */
    connectRetryDelay = INITIAL_RECONNECT_DELAY;
    sequence = 0;
    /** @type {RTCDataChannel} */
    dataChannel;
    hasPriority = false;
    isBuildingOffer = false;
    isBuildingAnswer = false;
    /** @type {Object<STREAM_TYPE[keyof STREAM_TYPE], Media>} */
    medias = Object.seal({
        [STREAM_TYPE.AUDIO]: {
            track: null,
            active: false,
            accepted: true,
        },
        [STREAM_TYPE.SCREEN]: {
            track: null,
            active: false,
            accepted: true,
        },
        [STREAM_TYPE.CAMERA]: {
            track: null,
            active: false,
            accepted: true,
        },
    });
    /**
     * @param {number} id
     * @param {Object} param2
     * @param {RTCPeerConnection} param2.connection
     * @param {RTCDataChannel} param2.dataChannel
     * @param {boolean} [param2.hasPriority=false]
     * @param {number} [param2.connectRetryDelay=INITIAL_RECONNECT_DELAY]
     * @param {number} [param2.sequence=0]
     */
    constructor(
        id,
        {
            connection,
            dataChannel,
            hasPriority = false,
            connectRetryDelay = INITIAL_RECONNECT_DELAY,
            sequence = 0,
        },
    ) {
        this.id = id;
        this.connection = connection;
        this.dataChannel = dataChannel;
        this.hasPriority = hasPriority;
        this.connectRetryDelay = connectRetryDelay;
        this.sequence = sequence;
        this.ready = new Deferred();
    }

    disconnect() {
        if (this.connection) {
            const RTCRtpSenders = this.connection.getSenders();
            for (const sender of RTCRtpSenders) {
                try {
                    this.connection.removeTrack(sender);
                } catch {}
            }
            for (const transceiver of this.connection.getTransceivers()) {
                try {
                    transceiver.stop();
                } catch {}
            }
        }
        this.ready.resolve?.();
        this.connection?.close();
        this.connection = undefined;
        this.dataChannel?.close();
        this.dataChannel = undefined;
        for (const media of Object.values(this.medias)) {
            media.track?.stop();
        }
    }
    /**
     * @param {STREAM_TYPE[keyof STREAM_TYPE]} streamType
     * @param {boolean} canUpload
     * @returns {RTCRtpTransceiverDirection}
     */
    getRecommendedTransceiverDirection(streamType, canUpload = false) {
        if (this.medias[streamType].accepted) {
            return canUpload ? "sendrecv" : "recvonly";
        } else {
            return canUpload ? "sendonly" : "inactive";
        }
    }
    /**
     * @param {STREAM_TYPE[keyof STREAM_TYPE]} streamType
     * @returns {RTCRtpTransceiver | undefined}
     */
    getTransceiver(streamType) {
        if (!this.connection) {
            return;
        }
        const transceivers = this.connection.getTransceivers();
        return transceivers[ORDERED_TRANSCEIVER_TYPES.indexOf(streamType)];
    }
    /**
     * @param {RTCRtpTransceiver} transceiver
     * @returns {STREAM_TYPE[keyof STREAM_TYPE]}
     */
    getTransceiverStreamType(transceiver) {
        const transceivers = this.connection.getTransceivers();
        return ORDERED_TRANSCEIVER_TYPES[transceivers.indexOf(transceiver)];
    }
}

export class PeerToPeer extends EventTarget {
    /** @type {number} */
    selfId;
    /** @type {number} */
    channelId;
    /** @type {Map<number, Peer>} */
    peers = new Map();
    /**
     * @param {number} id
     * @param {number} sequence
     */
    acceptOffer = async (id, sequence) => true;
    /** @type {number} */
    _batchDelay = DEFAULT_BUS_BATCH_DELAY;
    /** @type {Info} */
    _localInfo = Object.seal({
        isSelfMuted: false,
        isRaisingHand: false,
        isDeaf: false,
        isTalking: false,
        isCameraOn: false,
        isScreenSharingOn: false,
    });
    /** @type {Array<RTCIceServer>} */
    _iceServers;
    _isPendingNotify = false;
    /**
     * @type {Map<string|number, QueuedNotification>}
     */
    _notificationsToSend = new Map();
    _isAntiGlareEnabled = true;
    /** @type {number} */
    _tmpNotificationId = 0;
    /** @type {Map<number, number>} */
    _recoverTimeouts = new Map();
    /** @type {String} */
    _notificationRoute;
    /** @type {boolean} */
    _isStreamingEnabled = true;
    /** @type {Object<STREAM_TYPE[keyof STREAM_TYPE], MediaStreamTrack | null>} */
    _tracks = Object.seal({
        [STREAM_TYPE.AUDIO]: null,
        [STREAM_TYPE.SCREEN]: null,
        [STREAM_TYPE.CAMERA]: null,
    });
    /**
     * @type {Object<string, (id: number, message: string) => void>}
     */
    _loggingFunctions = {
        [LOG_LEVEL.DEBUG]: () => {},
        [LOG_LEVEL.INFO]: () => {},
        [LOG_LEVEL.WARN]: () => {},
        [LOG_LEVEL.ERROR]: () => {},
    };
    get isActive() {
        return Boolean(this.selfId !== undefined && this.channelId !== undefined);
    }
    /**
     * @param {object} [options]
     * @param {String} [options.notificationRoute]
     * @param {LOG_LEVEL[keyof LOG_LEVEL]} [options.logLevel=LOG_LEVEL.ERROR]
     * @param {boolean} [options.antiGlare=true]
     * @param {number} [options.batchDelay=DEFAULT_BUS_BATCH_DELAY]
     * @param {boolean} [options.enableStreaming=true]
     */
    constructor({
        notificationRoute = DEFAULT_NOTIFICATION_ROUTE,
        logLevel = LOG_LEVEL.ERROR,
        batchDelay = DEFAULT_BUS_BATCH_DELAY,
        antiGlare = true,
        enableStreaming = true,
    } = {}) {
        super();
        this._isStreamingEnabled = enableStreaming;
        this._isAntiGlareEnabled = antiGlare;
        this._notificationRoute = notificationRoute;
        this._batchDelay = batchDelay;
        this.setLoggingLevel(logLevel);
    }

    /**
     * @param {number} selfId
     * @param {number} channelId
     * @param {object} [options]
     * @param {Partial<Info>} [options.info={}]
     * @param {RTCIceServer[]} [options.iceServers=DEFAULT_ICE_SERVERS]
     */
    connect(selfId, channelId, { info = {}, iceServers = DEFAULT_ICE_SERVERS } = {}) {
        if (!IS_CLIENT_RTC_COMPATIBLE) {
            throw new Error("RTCPeerConnection is not supported");
        }
        this.selfId = selfId;
        this.channelId = channelId;
        this._iceServers = iceServers;
        this._localInfo = Object.assign(this._localInfo, info);
    }

    removeAllPeers() {
        for (const peer of this.peers.values()) {
            this.removePeer(peer.id);
        }
        this.peers.clear();
    }

    disconnect() {
        this.removeAllPeers();
        this.selfId = undefined;
        this.channelId = undefined;
        this._isPendingNotify = false;
        this._notificationsToSend.clear();
        this._localInfo = Object.assign(this._localInfo, {
            isSelfMuted: false,
            isRaisingHand: false,
            isDeaf: false,
            isTalking: false,
            isCameraOn: false,
            isScreenSharingOn: false,
        });
    }
    /**
     * @param {number} id
     * @param {object} [options={}]
     * @returns {Promise<Peer>}
     */
    async addPeer(id, options = {}) {
        const peer = this.peers.get(id);
        if (peer) {
            return peer;
        }
        const newPeer = this._createPeer(id, options);
        await newPeer.ready;
        return newPeer;
    }
    /** @param {number} id */
    removePeer(id) {
        const recoverTimeoutId = this._recoverTimeouts.get(id);
        browser.clearTimeout(recoverTimeoutId);
        this._recoverTimeouts.delete(id);
        const peer = this.peers.get(id);
        if (!peer) {
            return;
        }
        this.peers.delete(id);
        peer.disconnect();
    }

    /** @param {any} message */
    broadcast(message) {
        this._dataChannelBroadcast(INTERNAL_EVENT.BROADCAST, message);
    }
    /**
     * @param {number} id
     * @return {Promise<FormattedPeerStats>}
     */
    async getFormattedStats(id) {
        const peer = this.peers.get(id);
        /** @type {FormattedPeerStats} */
        const formattedStats = {};
        if (!peer) {
            return formattedStats;
        }
        formattedStats.connectionState = peer.connection.connectionState;
        formattedStats.iceConnectionState = peer.connection.iceConnectionState;
        formattedStats.iceGatheringState = peer.connection.iceGatheringState;
        const stats = await peer.connection.getStats();
        for (const value of stats?.values() || []) {
            switch (value.type) {
                case "candidate-pair":
                    if (value.state === "succeeded" && value.localCandidateId) {
                        formattedStats.localCandidateType =
                            stats.get(value.localCandidateId)?.candidateType || "";
                        formattedStats.remoteCandidateType =
                            stats.get(value.remoteCandidateId)?.candidateType || "";
                    }
                    break;
                case "data-channel":
                    formattedStats.dataChannelState = value.state;
                    break;
                case "transport":
                    formattedStats.dtlsState = value.dtlsState;
                    formattedStats.iceState = value.iceState;
                    formattedStats.packetsReceived = value.packetsReceived;
                    formattedStats.packetsSent = value.packetsSent;
                    break;
            }
        }
        return formattedStats;
    }
    /**
     * @param {number} id
     * @param {Object<string, boolean>} states
     */
    updateDownload(id, states) {
        const peer = this.peers.get(id);
        if (!peer) {
            return;
        }
        for (const [rawStreamType, accepted] of Object.entries(states)) {
            const streamType = /** @type {STREAM_TYPE[keyof STREAM_TYPE]} */ (
                rawStreamType
            );
            peer.medias[streamType].accepted = accepted;
            const transceiver = peer.getTransceiver(streamType);
            if (!transceiver) {
                this._recover(id, `no transceiver available when updating direction`);
                continue;
            }
            transceiver.direction = peer.getRecommendedTransceiverDirection(
                streamType,
                Boolean(this._tracks[streamType]),
            );
        }
    }

    /**
     * @param {STREAM_TYPE[keyof STREAM_TYPE]} streamType
     * @param {MediaStreamTrack | null} [track]
     */
    async updateUpload(streamType, track) {
        this._tracks[streamType] = track || null;
        this.updateInfo({
            isScreenSharingOn: Boolean(this._tracks[STREAM_TYPE.SCREEN]),
            isCameraOn: Boolean(this._tracks[STREAM_TYPE.CAMERA]),
        });
        for (const peer of this.peers.values()) {
            peer.ready.then(() => this._updateRemote(peer, streamType));
        }
    }
    /** @param {Partial<Info>} info */
    updateInfo(info) {
        this._localInfo = Object.assign(this._localInfo, info);
        this._dataChannelBroadcast(INTERNAL_EVENT.INFO, this._localInfo);
    }
    /**
     * @param {number} id
     * @param {string} content
     */
    async handleNotification(id, content) {
        /**
         * @type {{ event: INTERNAL_EVENT[keyof INTERNAL_EVENT], channelId: number, payload: NotificationPayload, }}
         */
        let notification;
        try {
            notification = JSON.parse(content);
        } catch {
            this._emitLog(id, `discarded unparsable notification`, LOG_LEVEL.WARN);
            return;
        }
        const { event, channelId, payload } = notification;
        this._emitLog(id, `received notification: ${event}`, LOG_LEVEL.DEBUG);
        if (channelId !== this.channelId) {
            return;
        }
        let peer = this.peers.get(id);
        if (event !== INTERNAL_EVENT.OFFER && !peer?.connection) {
            this._emitLog(
                id,
                `received ${event} for missing peer ${id}`,
                LOG_LEVEL.WARN,
            );
            return;
        }
        switch (event) {
            case INTERNAL_EVENT.ANSWER: {
                this._emitLog(id, `received answer`, LOG_LEVEL.DEBUG);
                if (
                    INVALID_ICE_CONNECTION_STATES.has(
                        peer.connection.iceConnectionState,
                    ) ||
                    peer.connection.signalingState === "stable" ||
                    peer.connection.signalingState === "have-remote-offer"
                ) {
                    return;
                }
                const description = new window.RTCSessionDescription(payload.sdp);
                try {
                    await peer.connection.setRemoteDescription(description);
                } catch {
                    this._recover(
                        id,
                        "answer handling: Failed at setting remoteDescription",
                    );
                }
                break;
            }
            case INTERNAL_EVENT.BROADCAST: {
                this._emitUpdate({
                    name: UPDATE_EVENT.BROADCAST,
                    payload: { senderId: id, message: payload },
                });
                peer.ready.resolve(true);
                break;
            }
            case INTERNAL_EVENT.DISCONNECT: {
                this.removePeer(id);
                this._emitUpdate({
                    name: UPDATE_EVENT.DISCONNECT,
                    payload: { sessionId: id },
                });
                break;
            }
            case INTERNAL_EVENT.ICE_CANDIDATE: {
                if (
                    INVALID_ICE_CONNECTION_STATES.has(
                        peer.connection.iceConnectionState,
                    )
                ) {
                    return;
                }
                const rtcIceCandidate = new window.RTCIceCandidate(payload.candidate);
                try {
                    await peer.connection.addIceCandidate(rtcIceCandidate);
                } catch {
                    this._recover(id, "failed at adding ice candidate");
                }
                break;
            }
            case INTERNAL_EVENT.INFO: {
                const { isTalking, isCameraOn, isScreenSharingOn } = payload;
                peer.medias[STREAM_TYPE.AUDIO].active = isTalking;
                peer.medias[STREAM_TYPE.CAMERA].active = isCameraOn;
                peer.medias[STREAM_TYPE.SCREEN].active = isScreenSharingOn;
                this._emitUpdate({
                    name: UPDATE_EVENT.INFO_CHANGE,
                    payload: { [id]: payload },
                });
                break;
            }
            case INTERNAL_EVENT.OFFER: {
                try {
                    const accepted = await this.acceptOffer(id, payload.sequence);
                    if (!accepted) {
                        this._emitLog(id, "offer rejected", LOG_LEVEL.INFO);
                        return;
                    }
                } catch (error) {
                    this._emitLog(id, `offer rejected: ${error}`, LOG_LEVEL.INFO);
                    return;
                }
                if (!peer) {
                    peer = this._createPeer(id, { sequence: payload.sequence });
                }
                if (
                    !peer.connection ||
                    INVALID_ICE_CONNECTION_STATES.has(
                        peer.connection.iceConnectionState,
                    ) ||
                    peer.connection.signalingState === "have-remote-offer"
                ) {
                    return;
                }
                const isStable =
                    peer.connection.signalingState === "stable" ||
                    peer.isBuildingAnswer;
                const hasOfferCollision = !isStable || peer.isBuildingOffer;
                if (hasOfferCollision && peer.hasPriority && this._isAntiGlareEnabled) {
                    this._emitLog(
                        peer.id,
                        `rolling back due to offer collision: ${peer.connection.signalingState}`,
                        LOG_LEVEL.WARN,
                    );
                    try {
                        await peer.connection.setLocalDescription({ type: "rollback" });
                    } catch {
                        this._recover(id, `failed rollback`);
                    }
                }
                const description = new window.RTCSessionDescription(payload.sdp);
                try {
                    await peer.connection.setRemoteDescription(description);
                } catch {
                    this._recover(id, "failed at setting remoteDescription");
                    return;
                }
                if (!peer.connection) {
                    this._emitLog(
                        id,
                        "the peer connection was closed during offer negotiation",
                        LOG_LEVEL.WARN,
                    );
                    return;
                }
                if (this._isStreamingEnabled) {
                    if (peer.connection.getTransceivers().length === 0) {
                        for (const streamType of ORDERED_TRANSCEIVER_TYPES) {
                            const type =
                                streamType === STREAM_TYPE.AUDIO ? "audio" : "video";
                            peer.connection.addTransceiver(type);
                        }
                    }
                    for (const transceiverName of ORDERED_TRANSCEIVER_TYPES) {
                        await this._updateRemote(peer, transceiverName);
                    }
                }
                peer.isBuildingAnswer = true;
                try {
                    await peer.connection.setLocalDescription(
                        await peer.connection.createAnswer(),
                    );
                } catch {
                    peer.isBuildingAnswer = false;
                    this._recover(
                        id,
                        "offer handling: failed at setting answer localDescription",
                    );
                    return;
                }
                peer.isBuildingAnswer = false;
                if (!this.isActive || !this.peers.has(id)) {
                    return;
                }
                this._emitLog(id, `sending answer`, LOG_LEVEL.DEBUG);
                await this._busNotify(INTERNAL_EVENT.ANSWER, {
                    payload: {
                        sdp: peer.connection.localDescription,
                    },
                    targets: [peer.id],
                });
                this._recover(peer.id, "standard answer timeout");
                break;
            }
        }
    }
    /** @param {LOG_LEVEL[keyof LOG_LEVEL]} logLevel */
    setLoggingLevel(logLevel) {
        /** @param {LOG_LEVEL[keyof LOG_LEVEL]} level */
        const makeLog =
            (level) =>
            /**
             * @param {number} id
             * @param {string} message
             */
            (id, message) => {
                this.dispatchEvent(
                    new CustomEvent("log", { detail: { id, level, message } }),
                );
            };
        this._loggingFunctions = {
            [LOG_LEVEL.DEBUG]: () => {},
            [LOG_LEVEL.INFO]: () => {},
            [LOG_LEVEL.WARN]: () => {},
            [LOG_LEVEL.ERROR]: () => {},
        };
        switch (logLevel) {
            case LOG_LEVEL.DEBUG:
                this._loggingFunctions[LOG_LEVEL.DEBUG] = makeLog(LOG_LEVEL.DEBUG);
            // eslint-disable-next-line no-fallthrough
            case LOG_LEVEL.INFO:
                this._loggingFunctions[LOG_LEVEL.INFO] = makeLog(LOG_LEVEL.INFO);
            // eslint-disable-next-line no-fallthrough
            case LOG_LEVEL.WARN:
                this._loggingFunctions[LOG_LEVEL.WARN] = makeLog(LOG_LEVEL.WARN);
            // eslint-disable-next-line no-fallthrough
            case LOG_LEVEL.ERROR:
                this._loggingFunctions[LOG_LEVEL.ERROR] = makeLog(LOG_LEVEL.ERROR);
        }
    }
    /**
     * @param {INTERNAL_EVENT[keyof INTERNAL_EVENT]} internalEvent
     * @param {any} message
     */
    _dataChannelBroadcast(internalEvent, message) {
        for (const peer of this.peers.values()) {
            if (!peer?.dataChannel || peer?.dataChannel.readyState !== "open") {
                continue;
            }
            peer.dataChannel.send(
                JSON.stringify({
                    event: internalEvent,
                    channelId: this.channelId,
                    payload: message,
                }),
            );
        }
    }
    /** @param {any} detail */
    _emitUpdate(detail) {
        this.dispatchEvent(new CustomEvent("update", { detail }));
    }
    /**
     * @param {number} id
     * @param {string} message
     * @param {LOG_LEVEL[keyof LOG_LEVEL]} [level=LOG_LEVEL.DEBUG]
     */
    _emitLog(id, message, level = LOG_LEVEL.DEBUG) {
        this._loggingFunctions[level](id, message);
    }
    /**
     * @param {number} id
     * @param {string} reason
     */
    _recover(id, reason = "") {
        this._emitLog(id, `connection recovery candidate: ${reason}`, LOG_LEVEL.WARN);
        if (this._recoverTimeouts.has(id)) {
            return;
        }
        const peer = this.peers.get(id);
        if (!peer) {
            return;
        }
        const delay =
            Math.min(peer.connectRetryDelay * 1.5, MAXIMUM_RECONNECT_DELAY) +
            1000 * Math.random();
        this._recoverTimeouts.set(
            id,
            browser.setTimeout(async () => {
                const peer = this.peers.get(id);
                this._recoverTimeouts.delete(id);
                if (!peer?.connection || !this.channelId) {
                    return;
                }
                const connectionSuccess =
                    peer.connection.connectionState === "connected";
                const iceSuccess =
                    peer.connection.iceConnectionState === "connected" ||
                    peer.connection.iceConnectionState === "completed";
                if (connectionSuccess && iceSuccess) {
                    return;
                }
                if (
                    peer.connection.connectionState === "connecting" ||
                    peer.connection.iceConnectionState === "checking"
                ) {
                    this._recover(peer.id, `${reason} (still progressing)`);
                    return;
                }
                this._emitUpdate({ name: UPDATE_EVENT.RECOVERY, payload: { id } });
                this._emitLog(
                    id,
                    `attempting to recover connection: ${reason}`,
                    LOG_LEVEL.ERROR,
                );
                this._busNotify(INTERNAL_EVENT.DISCONNECT, { targets: [peer.id] });
                this.removePeer(peer.id);
                this.addPeer(peer.id, {
                    connectRetryDelay: delay,
                    sequence: peer.sequence,
                });
            }, delay),
        );
    }
    async _sendNotifications() {
        if (this._isPendingNotify) {
            return;
        }
        this._isPendingNotify = true;
        try {
            let failedAttempts = 0;
            let retryDelay = INITIAL_RECONNECT_DELAY;
            while (true) {
                await new Promise((resolve) =>
                    browser.setTimeout(resolve, this._batchDelay),
                );
                if (!this.isActive || this._notificationsToSend.size === 0) {
                    return;
                }
                /** @type {[string|number, QueuedNotification][]} */
                const sent = [];
                /** @type {[number, number[], string][]} */
                const notifications = [];
                this._notificationsToSend.forEach((notification, id) => {
                    sent.push([id, notification]);
                    notifications.push([
                        notification.sender,
                        notification.targets,
                        JSON.stringify({
                            event: notification.event,
                            channelId: notification.channelId,
                            payload: notification.payload,
                        }),
                    ]);
                });
                try {
                    await rpc(
                        this._notificationRoute,
                        {
                            peer_notifications: notifications,
                        },
                        { silent: true },
                    );
                } catch {
                    failedAttempts++;
                    if (failedAttempts > MAX_NOTIFICATION_RETRIES) {
                        this._emitLog(
                            this.selfId,
                            "too many failed attempts to send notifications, giving up",
                            LOG_LEVEL.ERROR,
                        );
                        for (const [id, notification] of sent) {
                            if (this._notificationsToSend.get(id) === notification) {
                                this._notificationsToSend.delete(id);
                            }
                        }
                        return;
                    }
                    await new Promise((resolve) =>
                        browser.setTimeout(resolve, retryDelay),
                    );
                    retryDelay = Math.min(retryDelay * 1.5, MAXIMUM_RECONNECT_DELAY);
                    continue;
                }
                failedAttempts = 0;
                retryDelay = INITIAL_RECONNECT_DELAY;
                for (const [id, notification] of sent) {
                    if (this._notificationsToSend.get(id) === notification) {
                        this._notificationsToSend.delete(id);
                    }
                }
            }
        } finally {
            this._isPendingNotify = false;
        }
    }
    /**
     * @param {INTERNAL_EVENT[keyof INTERNAL_EVENT]} event
     * @param {Object} [options]
     * @param {Object} [options.payload]
     * @param {number[]} [options.targets]
     */
    async _busNotify(event, { payload, targets } = {}) {
        targets = targets || Array.from(this.peers.keys());
        let id;
        if (event === INTERNAL_EVENT.OFFER) {
            id = `latestOffer_to:${targets[0]}`;
        } else {
            id = ++this._tmpNotificationId;
        }
        this._notificationsToSend.set(id, {
            channelId: this.channelId,
            event,
            payload,
            sender: this.selfId,
            targets,
        });
        await this._sendNotifications();
    }
    /**
     * @param {Peer} peer
     * @param {STREAM_TYPE[keyof STREAM_TYPE]} streamType
     */
    async _updateRemote(peer, streamType) {
        const track = this._tracks[streamType];
        const transceiver = peer.getTransceiver(streamType);
        if (!transceiver) {
            return;
        }
        try {
            await transceiver.sender.replaceTrack(track);
            transceiver.direction = peer.getRecommendedTransceiverDirection(
                streamType,
                Boolean(track),
            );
        } catch (error) {
            this._recover(
                peer.id,
                `failed to update ${streamType} transceiver for peer ${peer.id}: ${error}`,
            );
        }
    }
    /**
     * @param {number} id
     * @param {object} [options={}]
     * @returns {Peer}
     */
    _createPeer(id, options = {}) {
        this.removePeer(id);
        const peerConnection = new window.RTCPeerConnection({
            iceServers: this._iceServers,
        });
        const dataChannel = peerConnection.createDataChannel("notifications", {
            negotiated: true,
            id: 1,
        });
        const peer = new Peer(id, {
            ...options,
            connection: peerConnection,
            dataChannel,
            hasPriority: id > this.selfId,
        });
        this._emitUpdate({
            name: UPDATE_EVENT.CONNECTION_CHANGE,
            payload: { id, peer, state: "searching for network" },
        });
        this.peers.set(id, peer);
        peerConnection.addEventListener(
            "icecandidate",
            /** @param {RTCPeerConnectionIceEvent} event */
            async (event) => {
                if (!event.candidate) {
                    return;
                }
                if (!this.isActive || !this.peers.has(id)) {
                    return;
                }
                await this._busNotify(INTERNAL_EVENT.ICE_CANDIDATE, {
                    payload: {
                        candidate: event.candidate,
                    },
                    targets: [id],
                });
            },
        );
        peerConnection.addEventListener("iceconnectionstatechange", async () => {
            switch (peerConnection.iceConnectionState) {
                case "closed":
                    this.removePeer(id);
                    break;
                case "failed":
                case "disconnected":
                    this._recover(peer.id, "ice connection disconnected");
                    break;
            }
        });
        peerConnection.addEventListener("icegatheringstatechange", () => {
            this._emitLog(
                id,
                `gathering state change: ${peerConnection.iceGatheringState}`,
                LOG_LEVEL.INFO,
            );
        });
        peerConnection.addEventListener("connectionstatechange", async () => {
            this._emitUpdate({
                name: UPDATE_EVENT.CONNECTION_CHANGE,
                payload: { id, peer, state: peerConnection.connectionState },
            });
            switch (peerConnection.connectionState) {
                case "closed":
                    this.removePeer(id);
                    break;
                case "failed":
                case "disconnected":
                    this._recover(peer.id, "connection disconnected");
                    break;
            }
            this._emitLog(
                id,
                `connection state change: ${peerConnection.connectionState}`,
                LOG_LEVEL.INFO,
            );
        });
        peerConnection.addEventListener(
            "icecandidateerror",
            /** @param {RTCPeerConnectionIceErrorEvent} error */
            async (error) => {
                this._recover(id, `ice candidate error: ${error.errorText}`);
            },
        );
        peerConnection.addEventListener("negotiationneeded", async () => {
            peer.isBuildingOffer = true;
            try {
                await peerConnection.setLocalDescription(
                    await peerConnection.createOffer(),
                );
            } catch (error) {
                this._recover(
                    id,
                    `failed to set local Description for offer: ${error}`,
                );
                peer.isBuildingOffer = false;
                return;
            }
            peer.isBuildingOffer = false;
            if (!this.isActive || !this.peers.has(id)) {
                return;
            }
            await this._busNotify(INTERNAL_EVENT.OFFER, {
                payload: {
                    sdp: peerConnection.localDescription,
                    sequence: peer.sequence,
                },
                targets: [id],
            });
        });
        peerConnection.addEventListener(
            "track",
            /** @param {RTCTrackEvent} ev */
            async ({ transceiver, track }) => {
                if (!peer?.id || !this.peers.has(peer.id)) {
                    return;
                }
                const streamType = peer.getTransceiverStreamType(transceiver);
                if (!streamType) {
                    this._recover(id, "received track for unknown transceiver");
                    return;
                }
                peer.medias[streamType].track = track;
                if (!(await peer.ready)) {
                    return;
                }
                this._emitUpdate({
                    name: UPDATE_EVENT.TRACK,
                    payload: {
                        sessionId: id,
                        type: streamType,
                        track,
                        active: peer.medias[streamType].active,
                        sequence: peer.sequence,
                    },
                });
            },
        );
        dataChannel.addEventListener(
            "message",
            /** @param {MessageEvent} event */
            async (event) => {
                await this.handleNotification(id, event.data);
            },
        );
        dataChannel.addEventListener("open", () => {
            if (dataChannel.readyState !== "open") {
                return;
            }
            dataChannel.send(
                JSON.stringify({
                    event: INTERNAL_EVENT.INFO,
                    channelId: this.channelId,
                    payload: this._localInfo,
                }),
            );
            this.broadcast({ sequence: peer.sequence });
        });
        return peer;
    }
}
