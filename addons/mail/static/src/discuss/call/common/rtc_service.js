/** @odoo-module native */
import { fields, Record } from "@mail/core/common/record";
import { CallInfiniteMirroringWarning } from "@mail/discuss/call/common/call_infinite_mirroring_warning";
import { CallPermissionDialog } from "@mail/discuss/call/common/call_permission_dialog";
import {
    CallTransport,
    CONNECTION_TYPES,
    hasTurn,
} from "@mail/discuss/call/common/call_transport";
import { CrossTabSync, PING_INTERVAL } from "@mail/discuss/call/common/cross_tab_sync";
import { LocalMediaController } from "@mail/discuss/call/common/local_media_controller";
import { CALL_PROMOTE_FULLSCREEN } from "@mail/discuss/call/common/thread_model_patch";
import { assignDefined, closeStream, onChange } from "@mail/utils/common/misc";
import { reactive, toRaw } from "@odoo/owl";
import { browser } from "@web/core/browser/browser";
import { isBrowserSafari, isMobileOS } from "@web/core/browser/feature_detection";
import { _t } from "@web/core/l10n/translation";
import { rpc } from "@web/core/network/rpc";
import { registry } from "@web/core/registry";
import { pick } from "@web/core/utils/collections/objects";
import { debounce } from "@web/core/utils/timing";

import { CallAction } from "./call_actions.js";

// re-exported from their new homes to keep the historical import path stable
// (tests and downstream modules import these from rtc_service).
export { CONNECTION_TYPES, Network } from "@mail/discuss/call/common/call_transport";
export {
    CROSS_TAB_CLIENT_MESSAGE,
    CROSS_TAB_HOST_MESSAGE,
} from "@mail/discuss/call/common/cross_tab_sync";

/**
 * @typedef {'audio' | 'camera' | 'screen' } streamType
 */

/**
 *
 * @param {EventTarget} target
 * @param {string} event
 * @param {Function} f event listener callback
 * @return {Function} unsubscribe function
 */
function subscribe(target, event, f) {
    target.addEventListener(event, f);
    return () => target.removeEventListener(event, f);
}

export const PTT_RELEASE_DURATION = 200;
const SW_MESSAGE_TYPE = {
    POST_RTC_LOGS: "POST_RTC_LOGS",
};

const IS_CLIENT_RTC_COMPATIBLE = Boolean(
    window.RTCPeerConnection && window.MediaStream,
);
function GET_DEFAULT_ICE_SERVERS() {
    return [
        { urls: ["stun:stun1.l.google.com:19302", "stun:stun2.l.google.com:19302"] },
    ];
}
/**
 * How long a session info payload may wait for its session record before it is
 * dropped: applying an update parked for a long time on `getWhenReady` would
 * overwrite fresher state with stale data.
 */
const SESSION_INFO_APPLY_TIMEOUT = 5_000;
const UNAVAILABLE_AS_REMOTE = _t("This action can only be done in the call tab.");
const CALL_FULLSCREEN_ID = Symbol("CALL_FULLSCREEN");

export class Rtc extends Record {
    notifications = reactive(new Map());
    /** @type {Map<string, number>} timeoutId by notificationId for call notifications */
    timeouts = new Map();
    /** @type {Map<number, number>} timeoutId by sessionId for download pausing delay */
    downloadTimeouts = new Map();
    /** @type {{urls: string[]}[]} */
    iceServers = fields.Attr(undefined, {
        compute() {
            return this.iceServers ? this.iceServers : GET_DEFAULT_ICE_SERVERS();
        },
    });
    /** @type {"granted" | "denied" | "prompt" | undefined} */
    microphonePermission;
    /** @type {"granted" | "denied" | "prompt" | undefined} */
    cameraPermission;
    /**
     * The RtcSession of the current user for the call hosted by this tab, this is only set if
     * the current tab is the cross-tab host (the tab that is maintaining the connections and streams).
     *
     * If you want a reference to the RtcSession of the call, regardless of where it is hosted,
     * as long as it is on the same browser, use `selfSession`.
     */
    localSession = fields.One("discuss.channel.rtc.session");
    /**
     * The RtcSession shared between tabs, this is set if any of the tabs of that browser is in a call.
     *
     * For most use cases, this is the RtcSession you want to use (to ensure cross-tab consistency),
     * unless you need to access actual connection data (connection stats, streams,...), which can only
     * be accessed from the tab that is hosting the call.
     */
    selfSession = fields.One("discuss.channel.rtc.session", {
        compute() {
            return (
                this.localSession ||
                this.store["discuss.channel.rtc.session"].get(
                    this.state.remoteSessionId,
                )
            );
        },
        onDelete() {
            if (this.channel) {
                this.channel.promoteFullscreen = CALL_PROMOTE_FULLSCREEN.INACTIVE;
            }
        },
    });
    channel = fields.One("Thread", {
        compute() {
            if (this.state.channel) {
                return this.state.channel;
            }
            if (this.state.remoteChannelId) {
                return this.store.Thread.insert({
                    model: "discuss.channel",
                    id: this.state.remoteChannelId,
                });
            }
        },
        onUpdate() {
            if (!this.channel) {
                return;
            }
            this.store.Thread.getOrFetch({
                model: "discuss.channel",
                id: this.channel.id,
            });
        },
    });
    /**
     * Html element embedding the rtc service. Used to scope the dialog to the correct
     * document fragment (either the actual document or the active shadow root).
     * @type {HTMLElement|undefined}
     */
    rootEl;
    /**
     * Network/SfuClient lifecycle component (created in `start()`).
     * @type {import("@mail/discuss/call/common/call_transport").CallTransport}
     */
    transport;
    /**
     * Local MediaStreamTrack ownership component (created in `start()`).
     * @type {import("@mail/discuss/call/common/local_media_controller").LocalMediaController}
     */
    media;
    /**
     * Cross-tab host/remote protocol component (created in `start()`).
     * @type {import("@mail/discuss/call/common/cross_tab_sync").CrossTabSync}
     */
    crossTab;

    /** @type {Object<string, boolean>} The keys are action names and the values are booleans indicating whether each action is active */
    lastActions = {};
    /** @type {Array<string>} Array of action names representing the stack of currently active actions */
    actionsStack = [];
    /** @type {string|undefined} String representing the last call action activated, or undefined if none are */
    lastSelfCallAction = undefined;
    /** callbacks to be called when cleaning the state up after a call */
    cleanups = [];
    /**
     * Monotonic write stamp of the last session info received, by session id.
     * Used to drop out-of-order/stale info applications.
     * @type {Map<number, number>}
     */
    _sessionInfoStamps = new Map();
    /** @type {number} id of the keep-alive interval started in `start()` */
    _pingIntervalId;

    /** @type {import("@mail/discuss/call/common/call_transport").Network|undefined} */
    get network() {
        return this.transport?.network;
    }
    /** @type {import("@mail/../lib/odoo_sfu/odoo_sfu").SfuClient|undefined} */
    get sfuClient() {
        return this.transport?.sfuClient;
    }
    get serverInfo() {
        return this.transport?.serverInfo;
    }
    set serverInfo(serverInfo) {
        // call data only exists once `start()` has created the transport
        this.transport.serverInfo = serverInfo;
    }

    /**
     * Whether this tab serves as a remote for a call hosted on another tab.
     */
    get isRemote() {
        return Boolean(this.state.remoteChannelId);
    }
    /**
     * Whether the current tab is the host of the call.
     */
    get isHost() {
        return Boolean(this.localSession);
    }

    callActions = fields.Attr([], {
        compute() {
            const transformedActions = registry
                .category("discuss.call/actions")
                .getEntries()
                .map(
                    ([id, definition]) =>
                        new CallAction({ owner: this, id, definition }),
                );
            for (const action of transformedActions) {
                action.setup();
            }
            return transformedActions;
        },
        onUpdate() {
            for (const action of this.callActions) {
                if (action.isActive === this.lastActions[action.id]) {
                    continue;
                }
                if (!action.isTracked) {
                    continue;
                }
                if (action.isActive) {
                    if (!this.actionsStack.includes(action.id)) {
                        this.actionsStack.unshift(action.id);
                    }
                } else {
                    this.actionsStack.splice(this.actionsStack.indexOf(action.id), 1);
                }
            }
            this.lastSelfCallAction = this.actionsStack[0];
            this.lastActions = Object.fromEntries(
                this.callActions.map((action) => [action.id, action.isActive]),
            );
        },
    });

    setup() {
        this.state = reactive({
            connectionType: undefined,
            hasPendingRequest: false,
            channel: undefined,
            logs: {},
            sendCamera: false,
            sendScreen: false,
            updateAndBroadcastDebounce: undefined,
            micAudioTrack: undefined,
            screenAudioTrack: undefined,
            audioTrack: undefined,
            cameraTrack: undefined,
            screenTrack: undefined,
            /**
             * callback to properly end the audio monitoring.
             * If set it indicates that we are currently monitoring the local
             * micAudioTrack for the voice activation feature.
             */
            disconnectAudioMonitor: undefined,
            pttReleaseTimeout: undefined,
            sourceCameraStream: null,
            sourceScreenStream: null,
            /**
             * Whether the network fell back to p2p mode in a SFU call.
             */
            fallbackMode: false,
            isPipMode: false,
            isFullscreen: false,
            /**
             * Id of the rtc session/channel of the call hosted by a tab of
             * this browser, as advertised over the BroadcastChannel. Written
             * by `CrossTabSync`; read by the `selfSession`/`channel` computes.
             */
            remoteSessionId: undefined,
            remoteChannelId: undefined,
        });
    }

    start() {
        const services = this.store.env.services;
        this.notification = services.notification;
        this.overlay = services.overlay;
        this.dialog = services.dialog;
        this.soundEffectsService = services["mail.sound_effects"];
        this.pttExtService = services["discuss.ptt_extension"];
        /**
         * @type {import("@mail/discuss/call/common/peer_to_peer").PeerToPeer}
         */
        this.p2pService = services["discuss.p2p"];
        this.transport = new CallTransport({
            getP2p: () => this.p2pService,
            state: this.state,
            hooks: {
                getIceServers: () => this.iceServers,
                getFreshInfo: () => {
                    this._syncVideoInfo();
                    return this.formatInfo();
                },
                getPeerSessionIds: () =>
                    this.state.channel
                        ? this.state.channel.rtc_session_ids
                              .filter((session) => session.notEq(this.localSession))
                              .map((session) => session.id)
                        : [],
                setLocalConnectionState: (connectionState) => {
                    this.localSession.connectionState = connectionState;
                },
                updateUpload: () => this.updateUpload(),
                onNetworkUpdate: (event) => this._handleNetworkUpdates(event),
                onNetworkLog: ({ detail: { id, level, message } }) => {
                    const session = this.store["discuss.channel.rtc.session"].get(id);
                    if (session) {
                        this.log(session, message, {
                            step: "p2p",
                            level,
                            important: true,
                        });
                    }
                },
                log: (entry, options) => this.log(this.localSession, entry, options),
                notify: (text) => this.notification.add(text, { type: "warning" }),
                leaveCall: () => this.leaveCall(),
            },
        });
        this.media = new LocalMediaController({
            state: this.state,
            hooks: {
                getSettings: () => this.store.settings,
                getLocalSession: () => this.localSession,
                getSelfSession: () => this.selfSession,
                updateTrackUpload: (type, track) =>
                    this._updateTrackUpload(type, track),
                setMute: (isMute) => this.setMute(isMute),
                onMediaUnavailable: (media) => this.showMediaUnavailableWarning(media),
                toggleVideo: (type, options) => this.toggleVideo(type, options),
                playSound: (soundName) => this.soundEffectsService.play(soundName),
                notify: (text) => this.notification.add(text, { type: "warning" }),
                setTalking: (isTalking) => this.setTalking(isTalking),
                refreshMicAudioStatus: () => this.refreshMicAudioStatus(),
            },
        });
        this.crossTab = new CrossTabSync({
            state: this.state,
            hooks: {
                isHost: () => this.isHost,
                onRemoteUpdate: (changes) => this.updateSessionInfo(changes),
                onHostClosed: () => this.clear(),
                onPipChange: (isPipMode) => {
                    this.state.isPipMode = isPipMode;
                },
                onRemoteTabInit: () => {
                    this._updateRemoteTabs({
                        [this.localSession.id]: toRaw(this.formatInfo()),
                    });
                    this.crossTab.notifyPipChange(this.state.isPipMode);
                },
                onActionRequest: async (changes) => {
                    await this._localAction(changes);
                    this._updateRemoteTabs({
                        [this.localSession.id]: toRaw(this.formatInfo()),
                    });
                },
                onLeaveRequest: () => this.leaveCall(this.channel),
                onVolumeChange: (changes) => {
                    const session = this.store["discuss.channel.rtc.session"].get(
                        changes.sessionId,
                    );
                    if (!session) {
                        return;
                    }
                    session.volume = changes.volume;
                },
                log: (entry, options) => this.log(this.selfSession, entry, options),
            },
        });
        this.crossTab.start();
        onChange(this.store.settings, "useBlur", () => {
            if (this.state.sendCamera) {
                this.toggleVideo("camera", { force: true });
            }
        });
        onChange(
            this.store.settings,
            ["edgeBlurAmount", "backgroundBlurAmount"],
            () => {
                if (this.media.blurManager) {
                    this.media.blurManager.edgeBlur =
                        this.store.settings.edgeBlurAmount;
                    this.media.blurManager.backgroundBlur =
                        this.store.settings.backgroundBlurAmount;
                }
            },
        );
        onChange(
            this.store.settings,
            ["voiceActivationThreshold", "use_push_to_talk"],
            () => {
                this.media.linkVoiceActivationDebounce();
            },
        );
        onChange(this.store.settings, "audioInputDeviceId", async () => {
            if (this.localSession) {
                // restore the mute state: switching microphone while muted
                // must not silently unmute the user
                await this.resetMicAudioTrack({ force: true, unmute: false });
            }
        });
        onChange(this.store.settings, "audioOutputDeviceId", async () => {
            if (this.localSession) {
                await this.setOutputDevice(this.store.settings.audioOutputDeviceId);
            }
        });
        onChange(this.store.settings, "cameraInputDeviceId", async () => {
            if (this.localSession && this.state.cameraTrack) {
                await this.toggleVideo("camera", { force: true, refreshStream: true });
            }
        });
        this.store.env.bus.addEventListener("RTC-SERVICE:PLAY_MEDIA", () => {
            const channel = this.state.channel;
            if (!channel) {
                return;
            }
            for (const session of channel.rtc_session_ids) {
                session.playAudio();
            }
        });
        browser.addEventListener("blur", () => this.onBlur());
        browser.addEventListener(
            "keydown",
            (ev) => {
                this.onKeyDown(ev);
            },
            { capture: true },
        );
        browser.addEventListener(
            "keyup",
            (ev) => {
                this.onKeyUp(ev);
            },
            { capture: true },
        );

        browser.addEventListener("pagehide", () => {
            if (this.state.channel) {
                const data = JSON.stringify({
                    params: {
                        channel_id: this.state.channel.id,
                        session_id: this.selfSession.id,
                    },
                });
                const blob = new Blob([data], { type: "application/json" });
                // using sendBeacon allows sending a post request even when the
                // browser prevents async requests from firing when the browser
                // is closed. Alternatives like synchronous XHR are not reliable.
                browser.navigator.sendBeacon("/mail/rtc/channel/leave_call", blob);
                this.sfuClient?.disconnect();
            }
        });
        /**
         * Call all sessions for which no peerConnection is established at
         * a regular interval to try to recover any connection that failed
         * to start.
         *
         * This is distinct from this.recover which tries to restore
         * connections that were established but failed or timed out.
         */
        this._pingIntervalId = browser.setInterval(async () => {
            if (!this.localSession || !this.state.channel) {
                return;
            }
            this.crossTab.ping(this.localSession.id);
            try {
                await this.ping();
                if (!this.localSession || !this.state.channel) {
                    return;
                }
                await this.call();
            } catch {
                // best-effort keep-alive: a network blip must not surface as
                // an unhandled rejection, the next interval will retry.
            }
        }, PING_INTERVAL);
    }

    get displaySurface() {
        return this.state.sourceScreenStream?.getVideoTracks()[0]?.getSettings()
            .displaySurface;
    }

    isPushToTalkRelease(ev) {
        if (
            !this.state.channel ||
            !this.store.settings.use_push_to_talk ||
            (ev instanceof KeyboardEvent && !this.store.settings.isPushToTalkKey(ev)) ||
            !this.localSession.isTalking ||
            this.pttExtService.voiceActivated
        ) {
            return false;
        }
        return true;
    }

    onKeyDown(ev) {
        if (!this.store.settings.isPushToTalkKey(ev)) {
            return;
        }
        this.onPushToTalk();
    }

    onKeyUp(ev) {
        if (!this.isPushToTalkRelease(ev)) {
            return;
        }
        this.setPttReleaseTimeout();
    }

    onBlur() {
        if (!this.isPushToTalkRelease()) {
            return;
        }
        this.setPttReleaseTimeout();
    }

    showMirroringWarning() {
        this.state.screenTrack.enabled = false;
        const trackEndedFn = () => this.removeMirroringWarning?.();
        this.removeMirroringWarning = this.overlay.add(
            CallInfiniteMirroringWarning,
            {
                onClose: ({ stopScreensharing } = {}) => {
                    this.removeMirroringWarning({ stopScreensharing });
                },
            },
            {
                onRemove: ({ stopScreensharing } = {}) => {
                    if (stopScreensharing) {
                        this.toggleVideo("screen", false);
                    }
                    this.state.screenTrack?.removeEventListener("ended", trackEndedFn);
                    this.removeMirroringWarning = null;
                },
            },
        );
        this.state.screenTrack.addEventListener("ended", trackEndedFn, { once: true });
    }

    setPttReleaseTimeout(duration = PTT_RELEASE_DURATION) {
        // a keyup/blur pair may schedule twice: an orphaned timer would later
        // cut the mic in the middle of the next transmission.
        browser.clearTimeout(this.state.pttReleaseTimeout);
        this.state.pttReleaseTimeout = browser.setTimeout(
            () => {
                this.setTalking(false);
                // this.localSession is unset once the call is left: no beep
                if (this.localSession && !this.localSession.isMute) {
                    this.soundEffectsService.play("ptt-release");
                }
            },
            Math.max(this.store.settings.voice_active_duration || 0, duration),
        );
    }

    onPushToTalk() {
        if (
            !this.state.channel ||
            this.store.settings.isRegisteringKey ||
            !this.store.settings.use_push_to_talk
        ) {
            return;
        }
        browser.clearTimeout(this.state.pttReleaseTimeout);
        if (!this.localSession.isTalking && !this.localSession.isMute) {
            this.soundEffectsService.play("ptt-press");
        }
        this.setTalking(true);
    }

    async openPip(options) {
        if (this.isHost) {
            this.exitFullscreen();
            await this.pipService.openPip(options);
            return;
        }
        this.notification.add(UNAVAILABLE_AS_REMOTE, {
            type: "warning",
        });
    }

    closePip() {
        if (this.isHost) {
            this.pipService.closePip();
        } else {
            this._remoteAction({ pip: false });
        }
    }

    /**
     * @param {Object} param0
     * @param {any} param0.id
     * @param {string} param0.text
     * @param {number} [param0.delay]
     */
    addCallNotification({ id, text, delay = 3000 }) {
        if (this.notifications.has(id)) {
            return;
        }
        this.notifications.set(id, { id, text });
        this.timeouts.set(
            id,
            browser.setTimeout(() => {
                this.notifications.delete(id);
                this.timeouts.delete(id);
            }, delay),
        );
    }

    /**
     * @param {any} id
     */
    removeCallNotification(id) {
        browser.clearTimeout(this.timeouts.get(id));
        this.notifications.delete(id);
        this.timeouts.delete(id);
    }

    /**
     * Notifies the server and does the cleanup of the current call.
     */
    async leaveCall(channel = this.state.channel) {
        if (channel.eq(this.state.channel)) {
            // leaving another channel's call (e.g. rejecting an invitation)
            // must not exit the fullscreen of the ongoing call
            this.store.fullscreenChannel = null;
        }
        this.state.hasPendingRequest = true;
        try {
            await this.rpcLeaveCall(channel);
        } catch {
            // best-effort, like the `pagehide` beacon path: hanging up while
            // offline must still run the local cleanup, otherwise the mic and
            // camera stay live with no way to stop them.
        } finally {
            // a stuck flag would permanently disable every join/leave action
            this.state.hasPendingRequest = false;
        }
        this.endCall(channel);
    }

    /**
     * @param {import("models").Thread} [channel]
     */
    endCall(channel = this.state.channel) {
        if (channel.self_member_id) {
            channel.self_member_id.rtc_inviting_session_id = undefined;
        }
        channel.activeRtcSession = undefined;
        if (channel.eq(this.state.channel)) {
            // only when ending the active call: broadcasting CLOSE for an
            // unrelated channel (invitation reject) would tear down the
            // call this tab hosts or mirrors in another channel
            this._endHost();
            this.state.logs.end = new Date().toISOString();
            this.dumpLogs();
            this.pttExtService.unsubscribe();
            this.transport?.disconnect();
            this.clear();
            this.soundEffectsService.play("call-leave");
        }
    }

    async deafen() {
        if (this.isRemote) {
            this._remoteAction({ is_deaf: true });
            return;
        }
        await this.setDeaf(true);
        this.soundEffectsService.play("earphone-off");
    }

    /**
     * @param {import("models").RtcSession} session
     * @param {boolean} active
     */
    setRemoteRaiseHand(session, active) {
        if (Boolean(session.raisingHand) === active) {
            return;
        }
        Object.assign(session, {
            raisingHand: active ? new Date() : undefined,
        });
        const notificationId = "raise_hand_" + session.id;
        if (session.raisingHand) {
            this.addCallNotification({
                id: notificationId,
                text: _t("%s raised their hand", session.name),
            });
        } else {
            this.removeCallNotification(notificationId);
        }
    }

    setVolume(session, volume) {
        session.volume = volume;
        this.store.settings.saveVolumeSetting({
            guestId: session?.guest_id?.id,
            partnerId: session?.partner_id?.id,
            volume,
        });
        this.crossTab?.notifyVolume(session.id, volume);
    }

    async mute() {
        if (this.isRemote) {
            this._remoteAction({ is_muted: true });
            return;
        }
        await this.setMute(true);
        this.soundEffectsService.play("mic-off");
    }

    /** @param {Object} props Properties to pass to the meeting component. */
    async enterFullscreen(props) {
        const Meeting = registry.category("discuss.call/components").get("Meeting");
        this.store.fullscreenChannel = this.channel;
        await this.fullscreen.enter(Meeting, {
            id: CALL_FULLSCREEN_ID,
            keepBrowserHeader: true,
            props,
            rootId: this.rootEl?.getRootNode()?.host?.id,
        });
    }

    async exitFullscreen() {
        this.store.fullscreenChannel = null;
        await this.fullscreen.exit(CALL_FULLSCREEN_ID);
    }

    /**
     * @param {import("models").Thread} channel
     * @param {Object} [initialState={}]
     * @param {boolean} [initialState.audio]
     * @param {boolean} [initialState.camera]
     */
    async toggleCall(channel, { audio = true, camera } = {}) {
        if (channel.id === this.state.remoteChannelId) {
            this.crossTab.requestLeave();
            this.clear();
            return;
        }
        // Note: ``selfie_segmentation.js`` is shipped eagerly via
        // ``web.assets_backend`` (mail/__manifest__.py defines it under
        // the bundle so ``window.SelfieSegmentation`` is available
        // before any call starts).  A previous in-place ``loadJS``
        // wrapped in ``Promise.resolve(() => loadJS(...))`` was a
        // no-op (the arrow function was the resolved value, never
        // invoked), and even when fixed would have been redundant.
        // Removed 2026-05-10 — see machine_doc_v1/CONVENTIONS.md
        // §"Lazy-loading vendored libraries".
        if (this.state.hasPendingRequest) {
            return;
        }
        const isActiveCall = channel.eq(this.state.channel);
        if (this.state.channel) {
            await this.leaveCall(this.state.channel);
        }
        if (!isActiveCall) {
            const joinCallOpts = { audio, camera };
            if (this.microphonePermission !== "granted") {
                joinCallOpts.audio = false;
            }
            await this.joinCall(channel, joinCallOpts);
        }
    }

    async toggleCameraFacingMode() {
        this.store.settings.cameraFacingMode =
            this.store.settings.cameraFacingMode === "user" ? "environment" : "user";
        await this.toggleVideo("camera", { force: true, refreshStream: true });
    }

    async toggleDeafen() {
        if (this.selfSession.is_deaf) {
            await this.undeafen();
            if (this.selfSession.is_muted) {
                await this.unmute();
            }
        } else {
            await this.deafen();
        }
    }

    async toggleMicrophone() {
        if (this.selfSession.isMute) {
            if (this.selfSession.is_muted) {
                await this.unmute();
            }
            if (this.selfSession.is_deaf) {
                await this.undeafen();
            }
        } else {
            await this.mute();
        }
    }

    async undeafen() {
        if (this.isRemote) {
            this._remoteAction({ is_deaf: false });
            return;
        }
        await this.setDeaf(false);
        this.soundEffectsService.play("earphone-on");
    }

    /** @param {"microphone" | "camera"} media */
    showMediaPermissionDialog(media) {
        this.closeCallPermissionDialog = this.dialog.add(
            CallPermissionDialog,
            {
                media,
                useMicrophone: () => this.unmute(),
                useCamera: () =>
                    this.toggleVideo("camera", { force: true, refreshStream: true }),
            },
            { context: { root: { el: this.rootEl } } },
        );
    }

    showMediaUnavailableWarning({ microphone, camera, screen }) {
        let errorMessage;
        if (microphone && camera) {
            errorMessage = _t(
                "Camera and microphone access blocked. Enable in browser settings.",
            );
        } else if (camera) {
            errorMessage = _t("Camera access blocked. Enable in browser settings.");
        } else if (microphone) {
            errorMessage = _t("Microphone access blocked. Enable in browser settings.");
        } else if (screen) {
            errorMessage = _t(
                "Screen sharing access blocked. Enable in browser settings.",
            );
        }
        this.notification.add(errorMessage, { type: "warning" });
    }

    async askForBrowserPermission({ audio, video }) {
        try {
            const stream = await browser.navigator.mediaDevices.getUserMedia({
                audio: audio ? this.store.settings.audioConstraints : false,
                video: video ? this.store.settings.cameraConstraints : false,
            });
            if (isBrowserSafari() || isMobileOS()) {
                if (audio) {
                    this.microphonePermission = "granted";
                }
                if (video) {
                    this.cameraPermission = "granted";
                }
            }
            closeStream(stream);
        } catch {
            this.showMediaUnavailableWarning({ microphone: audio, camera: video });
        }
        if (audio && video) {
            return (
                this.microphonePermission === "granted" &&
                this.cameraPermission === "granted"
            );
        }
        return audio
            ? this.microphonePermission === "granted"
            : this.cameraPermission === "granted";
    }

    async unmute() {
        if (this.isRemote) {
            this._remoteAction({ is_muted: false });
            return;
        }
        if (this.microphonePermission === "prompt") {
            this.showMediaPermissionDialog("microphone");
            return;
        }
        if (this.state.micAudioTrack) {
            await this.setMute(false);
        } else {
            await this.resetMicAudioTrack({ force: true });
        }
        this.soundEffectsService.play("mic-on");
    }

    //----------------------------------------------------------------------
    // Private
    //----------------------------------------------------------------------

    /**
     * Best-effort update of one outbound track through the active network.
     * Never rejects: several call sites are fire-and-forget and would
     * otherwise leak unhandled rejections.
     *
     * @param {streamType} type
     * @param {MediaStreamTrack | undefined} track
     */
    async _updateTrackUpload(type, track) {
        try {
            await this.network?.updateUpload(type, track);
        } catch (error) {
            this.log(this.selfSession, `failed to update ${type} upload`, { error });
        }
    }

    updateUpload() {
        this._updateTrackUpload("audio", this.state.audioTrack);
        this._updateTrackUpload("camera", this.state.cameraTrack);
        this._updateTrackUpload("screen", this.state.screenTrack);
    }

    async _initConnection() {
        await this.transport.initConnection({
            sessionId: this.localSession.id,
            channelId: this.state.channel.id,
        });
    }

    /**
     * Send an action to the host tab of the call
     *
     * @param {Object} changes
     */
    _remoteAction(changes) {
        this.crossTab.requestAction(changes);
    }

    _updateInfo() {
        if (!this.isHost) {
            return;
        }
        const info = toRaw(this.formatInfo());
        this.network?.updateInfo(info);
        this._updateRemoteTabs({ [this.localSession.id]: info });
    }

    _host() {
        this.crossTab.host(this.localSession.id);
        this._updateRemoteTabs({ [this.localSession.id]: toRaw(this.formatInfo()) });
    }
    _endHost() {
        this.crossTab?.endHost();
    }

    _updateRemoteTabs(changes) {
        this.crossTab.updateRemoteTabs(
            this.state.channel.id,
            this.localSession.id,
            changes,
        );
    }

    _postToTabs(message) {
        this.crossTab?.post(message);
    }

    async _localAction(actions = {}) {
        const promises = [];
        for (const [key, value] of Object.entries(actions)) {
            switch (key) {
                case "is_muted":
                    if (value === this.localSession.is_muted) {
                        break;
                    }
                    promises.push(value ? this.mute() : this.unmute());
                    break;
                case "is_deaf":
                    if (value === this.localSession.is_deaf) {
                        break;
                    }
                    value
                        ? promises.push(this.deafen())
                        : promises.push(this.undeafen());
                    break;
                case "raisingHand":
                    if (value === Boolean(this.localSession.raisingHand)) {
                        break;
                    }
                    promises.push(this.raiseHand(value));
                    break;
                case "pip":
                    if (value === this.state.isPipMode) {
                        break;
                    }
                    if (value) {
                        promises.push(this.openPip());
                    } else {
                        this.closePip();
                    }
                    break;
            }
        }
        await Promise.all(promises);
    }

    /**
     * @param {import("models").RtcSession} session
     * @param {String} entry
     * @param {Object} [param2]
     * @param {Error} [param2.error]
     * @param {String} [param2.step] current step of the flow
     * @param {String} [param2.state] current state of the connection
     * @param {Boolean} [param2.important] if the log is important and should be kept even if logRtc is disabled
     */
    log(session, entry, param2 = {}) {
        if (!session) {
            return;
        }
        const { error, step, state, important, ...data } = param2;
        session.logStep = entry;
        if (!this.store.settings.logRtc && !important) {
            return;
        }
        // eslint-disable-next-line no-console -- opt-in WebRTC call diagnostics logging
        console.debug(
            `%c${new Date().toLocaleString()} - [${entry}]`,
            "color: #e36f17; font-weight: bold;",
            toRaw(session)._raw,
            param2,
        );
        if (!this.state.logs) {
            return;
        }
        let sessionEntry = this.state.logs.entriesBySessionId[session.id];
        if (!sessionEntry) {
            this.state.logs.entriesBySessionId[session.id] = sessionEntry = {
                step: "",
                state: "",
                logs: [],
            };
        }
        if (step) {
            sessionEntry.step = step;
        }
        if (state) {
            sessionEntry.state = state;
        }
        sessionEntry.logs.push({
            event: `${new Date().toISOString()}: ${entry}`,
            error: error && {
                name: error.name,
                message: error.message,
                stack: error.stack && error.stack.split("\n"),
            },
            ...data,
        });
    }

    /**
     * @param {CustomEvent} param0
     * @param {Object} param0.detail
     * @param {String} param0.detail.name
     * @param {any} param0.detail.payload
     */
    async _handleNetworkUpdates({ detail: { name, payload } }) {
        if (!this.state.channel) {
            return;
        }
        switch (name) {
            case "broadcast":
                {
                    const {
                        senderId,
                        message: { sequence },
                    } = payload;
                    if (!sequence) {
                        return;
                    }
                    const session =
                        await this.store["discuss.channel.rtc.session"].getWhenReady(
                            senderId,
                        );
                    if (!session) {
                        return;
                    }
                    if (!session.sequence || session.sequence < sequence) {
                        session.sequence = sequence;
                    }
                }
                return;
            case "connection_change":
                {
                    const { id, state } = payload;
                    const session = this.store["discuss.channel.rtc.session"].get(id);
                    if (!session) {
                        return;
                    }
                    session.connectionState = state;
                }
                return;
            case "disconnect":
                {
                    const { sessionId } = payload;
                    const session =
                        this.store["discuss.channel.rtc.session"].get(sessionId);
                    if (!session) {
                        return;
                    }
                    this.disconnect(session);
                }
                return;
            case "info_change":
                this.updateSessionInfo(payload);
                return;
            case "track":
                {
                    const { sessionId, type, track, active, sequence } = payload;
                    const session =
                        await this.store["discuss.channel.rtc.session"].getWhenReady(
                            sessionId,
                        );
                    if (!session || !this.state.channel) {
                        this.log(
                            this.selfSession,
                            `track received for unknown session ${sessionId} (${this.state.connectionType})`,
                        );
                        return;
                    }
                    if (sequence && sequence < session.sequence) {
                        this.log(
                            session,
                            `track received for old sequence ${sequence} (${this.state.connectionType})`,
                        );
                        return;
                    }
                    this.log(
                        session,
                        `${type} track received (${this.state.connectionType})`,
                    );
                    try {
                        await this.handleRemoteTrack({ session, track, type, active });
                    } catch {
                        // ignored, the session may be closing.
                        // this can happen when you join a call from another tab in which you have another session.
                    }
                    // makes sure we are not downloading a video that is not displayed
                    browser.setTimeout(() => {
                        this.updateVideoDownload(session);
                    }, 2000);
                }
                return;
            case "recovery": {
                const { id } = payload;
                const session = this.store["discuss.channel.rtc.session"].get(id);
                if (
                    this.selfSession?.persona.main_user_id?.share !== false ||
                    this.serverInfo ||
                    this.state.fallbackMode ||
                    !session?.channel.eq(this.state.channel)
                ) {
                    return;
                }
                this.transport.onP2pRecovery(hasTurn(this.iceServers));
            }
        }
    }

    updateSessionInfo(payload) {
        if (!payload) {
            return;
        }
        if (this.isHost) {
            this._updateRemoteTabs(payload);
        }
        for (const [id, info] of Object.entries(payload)) {
            const sessionId = Number(id);
            // stamp each application so a payload parked on `getWhenReady`
            // cannot overwrite a fresher one once it resolves.
            const stamp = (this._sessionInfoStamps.get(sessionId) ?? 0) + 1;
            this._sessionInfoStamps.set(sessionId, stamp);
            this._applySessionInfo(sessionId, info, stamp);
        }
    }

    /**
     * @param {number} sessionId
     * @param {import("#src/models/session.js").SessionInfo} info
     * @param {number} stamp value of `_sessionInfoStamps` at scheduling time
     */
    async _applySessionInfo(sessionId, info, stamp) {
        const session = await Promise.race([
            this.store["discuss.channel.rtc.session"].getWhenReady(sessionId),
            // bounded wait: past this delay the info is likely stale, drop it
            // instead of applying it whenever the session finally shows up.
            new Promise((resolve) =>
                browser.setTimeout(resolve, SESSION_INFO_APPLY_TIMEOUT),
            ),
        ]);
        if (this._sessionInfoStamps.get(sessionId) !== stamp) {
            return; // a newer info payload for this session superseded this one
        }
        if (!session || session.eq(this.localSession) || !this.channel) {
            return;
        }
        // `isRaisingHand` is turned into the Date `raisingHand`
        this.setRemoteRaiseHand(session, info.isRaisingHand);
        assignDefined(session, {
            is_muted: info.isSelfMuted ?? info.is_muted,
            is_deaf: info.isDeaf ?? info.is_deaf,
            isTalking: info.isTalking,
            is_camera_on: info.isCameraOn ?? info.is_camera_on,
            is_screen_sharing_on: info.isScreenSharingOn ?? info.is_screen_sharing_on,
        });
    }

    /**
     * Connects to the other call participants through the current connection
     * type (see `CallTransport.call`).
     *
     * @param {Object} [options]
     * @param {boolean} [options.asFallback=false]
     * @return {Promise<void>}
     */
    async call(options) {
        // `?.`: out of a call (or before `start()`) there is no transport,
        // and the old implementation was a no-op in that situation too.
        return this.transport?.call(options);
    }

    /**
     * @param {import("models").RtcSession} session
     * @param {MediaStreamTrack} track
     * @param {streamType} type
     * @param {boolean} active false if the track is muted/disabled
     */
    async handleRemoteTrack({ session, track, type, active = true }) {
        session.updateStreamState(type, active);
        await this.updateStream(session, track, {
            mute: this.localSession.is_deaf,
            videoType: type,
        });
        this.updateActiveSession(session, type, { addVideo: true });
    }

    /**
     * @param {import("models").Thread} channel
     * @param {object} [initialState]
     * @param {boolean} [initialState.audio] whether to request and use the user audio input (microphone) at start
     * @param {boolean} [initialState.camera] whether to request and use the user video input (camera) at start
     */
    async joinCall(channel, { audio = true, camera = false } = {}) {
        if (!IS_CLIENT_RTC_COMPATIBLE) {
            this.notification.add(_t("Your browser does not support webRTC."), {
                type: "warning",
            });
            return;
        }
        this.pttExtService.subscribe();
        this.state.hasPendingRequest = true;
        let data;
        try {
            data = await rpc(
                "/mail/rtc/channel/join_call",
                {
                    camera,
                    channel_id: channel.id,
                    check_rtc_session_ids: channel.rtc_session_ids.map(
                        (session) => session.id,
                    ),
                },
                { silent: true },
            );
        } catch (error) {
            this.pttExtService.unsubscribe();
            throw error;
        } finally {
            // a stuck flag would permanently disable every join/leave action
            this.state.hasPendingRequest = false;
        }
        // Initializing a new session implies closing the current session.
        this.clear();
        this.state.channel = channel;
        this.store.insert(data);
        this.newLogs();
        this.state.updateAndBroadcastDebounce = debounce(
            async () => {
                if (!this.localSession) {
                    return;
                }
                await rpc(
                    "/mail/rtc/session/update_and_broadcast",
                    {
                        session_id: this.localSession.id,
                        values: pick(
                            this.localSession,
                            "is_camera_on",
                            "is_deaf",
                            "is_muted",
                            "is_screen_sharing_on",
                        ),
                    },
                    { silent: true },
                );
            },
            3000,
            { leading: true, trailing: true },
        );
        if (this.state.channel.self_member_id) {
            this.state.channel.self_member_id.rtc_inviting_session_id = undefined;
        }
        if (camera) {
            await this.toggleVideo("camera");
        }
        if (!this.selfSession) {
            return;
        }
        await this._initConnection();
        await this.resetMicAudioTrack({ force: audio });
        if (!this.state.channel?.id) {
            return;
        }
        this.soundEffectsService.play("call-join");
        this._host();
        this.cleanups.push(
            // only register the beforeunload event if there is a call as FireFox will not place
            // the pages with beforeunload listeners in the bfcache.
            subscribe(browser, "beforeunload", (event) => {
                event.preventDefault();
            }),
        );
        this.channel?.focusAvailableVideo();
    }

    newLogs() {
        this.state.logs = {
            channelId: this.state.channel.id,
            selfSessionId: this.localSession.id,
            start: new Date().toISOString(),
            hasTurn: hasTurn(this.iceServers),
            entriesBySessionId: {},
        };
    }

    /**
     * @param {Object} [param0={}]
     * @param  {boolean} [param0.download=false] true if we want to download the logs
     */
    dumpLogs({ download = false } = {}) {
        const logs = [];
        if (this.state.logs) {
            logs.push({
                type: "timeline",
                entry: this.state.logs.start,
                value: toRaw(this.state.logs),
            });
        }
        if (this.state.channel) {
            logs.push(this.buildSnapshot());
        }
        if (logs.length || download) {
            browser.navigator.serviceWorker?.controller?.postMessage({
                name: SW_MESSAGE_TYPE.POST_RTC_LOGS,
                logs,
                download,
            });
        }
    }

    buildSnapshot() {
        const server = {};
        if (this.state.connectionType === CONNECTION_TYPES.SERVER) {
            server.info = toRaw(this.serverInfo);
            server.state = this.sfuClient?.state;
            server.errors = this.sfuClient?.errors.map((error) => error.message);
        }
        const sessions = this.state.channel.rtc_session_ids.map((session) => {
            const sessionInfo = {
                id: session.id,
                channelMemberId: session.channel_member_id?.id,
                state: session.connectionState,
                audioError: session.audioError,
                videoError: session.videoError,
                sfuConsumers: this.network?.getSfuConsumerStats(session.id),
            };
            if (session.eq(this.selfSession)) {
                sessionInfo.isSelf = true;
            }
            const audioEl = session.audioElement;
            if (audioEl) {
                sessionInfo.audio = {
                    state: audioEl.readyState,
                    muted: audioEl.muted,
                    paused: audioEl.paused,
                    networkState: audioEl.networkState,
                };
            }
            const peer = this.p2pService?.peers.get(session.id);
            if (peer) {
                sessionInfo.peer = {
                    id: peer.id,
                    state: peer.connection.connectionState,
                    iceState: peer.connection.iceConnectionState,
                };
            }
            return sessionInfo;
        });
        return {
            type: "snapshot",
            entry: new Date().toISOString(),
            value: {
                server,
                sessions,
                connectionType: this.state.connectionType,
                fallback: this.state.fallbackMode,
            },
        };
    }

    logSnapshot() {
        if (!this.state.channel) {
            // a snapshot out of a call would not collect any data
            return;
        }
        browser.navigator.serviceWorker?.controller?.postMessage({
            name: SW_MESSAGE_TYPE.POST_RTC_LOGS,
            logs: [this.buildSnapshot()],
        });
    }

    async rpcLeaveCall(channel) {
        await rpc(
            "/mail/rtc/channel/leave_call",
            {
                channel_id: channel.id,
            },
            { silent: true },
        );
    }

    async ping() {
        const data = await rpc(
            "/discuss/channel/ping",
            {
                channel_id: this.state.channel.id,
                check_rtc_session_ids: this.state.channel.rtc_session_ids.map(
                    (session) => session.id,
                ),
                rtc_session_id: this.localSession.id,
            },
            { silent: true },
        );
        this.store.insert(data);
    }

    disconnect(session) {
        const downloadTimeout = this.downloadTimeouts.get(session.id);
        if (downloadTimeout) {
            clearTimeout(downloadTimeout);
            this.downloadTimeouts.delete(session.id);
        }
        this.removeCallNotification("raise_hand_" + session.id);
        session.raisingHand = undefined;
        session.logStep = undefined;
        session.audioError = undefined;
        session.videoError = undefined;
        session.connectionState = undefined;
        session.isTalking = false;
        session.mainVideoStreamType = undefined;
        this.removeAudioFromSession(session);
        this.removeVideoFromSession(session);
        this.p2pService?.removePeer(session.id);
        this.log(session, "peer removed", { step: "peer removed" });
    }

    clear() {
        if (this.state.channel) {
            for (const session of this.state.channel.rtc_session_ids) {
                this.removeAudioFromSession(session);
                this.removeVideoFromSession(session);
                session.isTalking = false;
            }
        }
        this.exitFullscreen();
        // cross-tab host bookkeeping and its watchdog timeout
        this.crossTab?.dispose();
        this._sessionInfoStamps.clear();
        for (const timeoutId of this.downloadTimeouts.values()) {
            browser.clearTimeout(timeoutId);
        }
        this.downloadTimeouts.clear();
        // stale call notifications (e.g. "raised hand") must not survive
        // into the next call.
        for (const timeoutId of this.timeouts.values()) {
            browser.clearTimeout(timeoutId);
        }
        this.timeouts.clear();
        this.notifications.clear();
        browser.clearTimeout(this.state.pttReleaseTimeout);
        this.cleanups.splice(0).forEach((cleanup) => cleanup());
        // aborts any in-flight `initConnection` run and resets the per-call
        // transport state (sfu timeout, clients, serverInfo, connectionType)
        this.transport?.dispose();
        this.closeCallPermissionDialog?.();
        this.state.updateAndBroadcastDebounce?.cancel();
        // stops every local track/stream, the audio mix and the blur pipeline
        this.media?.dispose();
        this.state.isPipMode = false;
        this.update({ localSession: undefined });
        Object.assign(this.state, {
            updateAndBroadcastDebounce: undefined,
            channel: undefined,
        });
        this.pipService?.closePip();
    }

    /**
     * @param {Boolean} is_deaf
     */
    async setDeaf(is_deaf) {
        this.updateAndBroadcast({ is_deaf });
        for (const session of this.state.channel.rtc_session_ids) {
            if (!session.audioElement) {
                continue;
            }
            session.audioElement.muted = is_deaf;
        }
        await this.refreshMicAudioStatus();
    }

    async setOutputDevice(deviceId) {
        const promises = [];
        for (const session of this.state.channel.rtc_session_ids) {
            if (!session.audioElement) {
                continue;
            }
            promises.push(session.audioElement.setSinkId(deviceId));
        }
        await Promise.all(promises);
    }

    /**
     * @param {Boolean} is_muted
     */
    async setMute(is_muted) {
        this.updateAndBroadcast({ is_muted });
        await this.refreshMicAudioStatus();
    }

    /**
     * @param {Boolean} raise
     */
    async raiseHand(raise) {
        if (this.isRemote) {
            this._remoteAction({ raisingHand: raise });
            return;
        }
        if (!this.localSession || !this.state.channel) {
            return;
        }
        this.localSession.raisingHand = raise ? new Date() : undefined;
        await this._updateInfo();
    }

    /**
     * @param {boolean} isTalking
     */
    async setTalking(isTalking) {
        if (!this.localSession || isTalking === this.localSession.isTalking) {
            return;
        }
        this.localSession.isTalking = isTalking;
        if (!this.localSession.isMute) {
            this.pttExtService.notifyIsTalking(isTalking);
            await this.refreshMicAudioStatus();
        }
    }

    /**
     * Applies blur effect to a video stream using BlurManager.
     *
     * @param {MediaStream} videoStream - input video stream.
     * @returns {Promise<BlurManager>} - BlurManager instance.
     */
    async applyBlurEffect(videoStream) {
        return this.media.applyBlurEffect(videoStream);
    }

    /**
     * @param {string} type
     * @param {Object} [param1]
     * @param {boolean} [param1.force]
     * @param {boolean} [param1.env]
     * @param {boolean} [param1.refreshStream]
     */
    async toggleVideo(type, options) {
        let force;
        let env;
        let refreshStream;
        if (typeof options === "boolean") {
            force = options;
        } else {
            force = options?.force;
            env = options?.env;
            refreshStream = options?.refreshStream;
        }
        if (this.isRemote) {
            this.notification.add(UNAVAILABLE_AS_REMOTE, {
                type: "warning",
            });
            return;
        }
        if (!this.state.channel?.id) {
            return;
        }
        switch (type) {
            case "camera": {
                if (this.cameraPermission === "prompt" && !this.state.cameraTrack) {
                    this.showMediaPermissionDialog("camera");
                    return;
                }
                const track = this.state.cameraTrack;
                const sendCamera = force ?? !this.state.sendCamera;
                this.state.sendCamera = false;
                await this.media.setVideo(track, type, {
                    activateVideo: sendCamera,
                    env,
                    refreshStream,
                });
                break;
            }
            case "screen": {
                const track = this.state.screenTrack;
                const sendScreen = force ?? !this.state.sendScreen;
                this.state.sendScreen = false;
                await this.media.setVideo(track, type, {
                    activateVideo: sendScreen,
                    env,
                });
                break;
            }
        }
        if (this.localSession) {
            switch (type) {
                case "camera": {
                    this.removeVideoFromSession(this.localSession, {
                        type: "camera",
                        cleanup: false,
                    });
                    if (this.state.cameraTrack) {
                        await this.updateStream(
                            this.localSession,
                            this.state.cameraTrack,
                        );
                    }
                    break;
                }
                case "screen": {
                    if (!this.state.screenTrack) {
                        this.removeVideoFromSession(this.localSession, {
                            type: "screen",
                            cleanup: false,
                        });
                    } else {
                        await this.updateStream(
                            this.localSession,
                            this.state.screenTrack,
                        );
                    }
                    break;
                }
            }
            // broadcast the new state before (and independently of) the
            // transport fan-out: the upload can lag for seconds behind a
            // stuck peer handshake and must not delay what the other
            // participants see.
            switch (type) {
                case "camera": {
                    this.updateAndBroadcast({
                        is_camera_on: !!this.state.sendCamera,
                    });
                    break;
                }
                case "screen": {
                    this.updateAndBroadcast({
                        is_screen_sharing_on: !!this.state.sendScreen,
                    });
                    break;
                }
            }
        }
        const updatedTrack =
            type === "camera" ? this.state.cameraTrack : this.state.screenTrack;
        await this._updateTrackUpload(type, updatedTrack);
    }

    updateAndBroadcast(data) {
        this._updateRemoteTabs({ [this.localSession.id]: data });
        assignDefined(this.localSession, data);
        this.state.updateAndBroadcastDebounce?.();
    }

    /**
     * Sets the enabled property of the local microphone audio track based on the
     * current session state. And notifies peers of the new audio state.
     */
    async refreshMicAudioStatus() {
        if (!this.state.micAudioTrack) {
            return;
        }
        this.media.applyMicState();
        this._updateInfo();
    }

    /**
     * @param {Object} param0
     * @param {boolean} [param0.force=false]
     * @param {boolean} [param0.unmute=true] see LocalMediaController
     */
    async resetMicAudioTrack({ force = false, unmute = true }) {
        return this.media.resetMicAudioTrack({ force, unmute });
    }

    /**
     * @param {import("models").id} id
     */
    deleteSession(id) {
        const session = this.store["discuss.channel.rtc.session"].get(id);
        if (session) {
            if (this.localSession && session.eq(this.localSession)) {
                this.notifyServerDisconnect();
                this.endCall();
            }
            this.disconnect(session);
            session.delete();
        }
    }

    notifyServerDisconnect() {
        this.log(this.localSession, "self session deleted by the server, ending call", {
            important: true,
        });
        this.notification.add(_t("Disconnected from the call by the server"), {
            type: "warning",
        });
    }

    /**
     * Pure read of the session info shared with the other call participants.
     * Callers that need the video flags realigned with the actual local
     * tracks must call `_syncVideoInfo()` first.
     */
    formatInfo() {
        return this.localSession.info;
    }

    /**
     * Realigns the shared video flags with the actual local tracks. To be
     * called before advertising the session info over a fresh transport
     * (`is_camera_on`/`is_screen_sharing_on` are otherwise maintained by
     * `toggleVideo`).
     */
    _syncVideoInfo() {
        this.localSession.is_camera_on = Boolean(this.state.cameraTrack);
        this.localSession.is_screen_sharing_on = Boolean(this.state.screenTrack);
    }

    /**
     * @param {import("models").RtcSession} session
     * @param {MediaStreamTrack} track
     * @param {Object} [parm1]
     * @param {boolean} [parm1.mute]
     * @param {"camera"|"screen"} [parm1.videoType]
     */
    async updateStream(session, track, { mute, videoType } = {}) {
        const stream = new window.MediaStream();
        stream.addTrack(track);
        if (track.kind === "audio") {
            const audioElement = session.audioElement || new window.Audio();
            audioElement.srcObject = stream;
            audioElement.load();
            audioElement.muted = mute;
            audioElement.volume = this.store.settings.getVolume(session);
            // Using both autoplay and play() as safari may prevent play() outside of user interactions
            // while some browsers may not support or block autoplay.
            audioElement.autoplay = true;
            session.audioElement = audioElement;
            session.audioStream = stream;
            session.is_muted = false;
            session.isTalking = false;
            await session.playAudio();
        }
        if (track.kind === "video") {
            videoType = videoType
                ? videoType
                : track.id === this.state.cameraTrack?.id
                  ? "camera"
                  : "screen";
            session.videoStreams.set(videoType, stream);
            this.updateActiveSession(session, videoType, { addVideo: true });
        }
    }

    /**
     * @param {import("models").RtcSession} session
     * @param {Object} [param1]
     * @param {String} [param1.type]
     * @param {boolean} [param1.cleanup]
     */
    removeVideoFromSession(session, { type, cleanup = true } = {}) {
        if (type) {
            this.updateActiveSession(session, type);
            if (cleanup) {
                closeStream(session.videoStreams.get(type));
            }
            session.videoStreams.delete(type);
            if (
                this.selfSession.videoStreams.size === 0 &&
                this.selfSession.eq(this.state.channel.activeRtcSession)
            ) {
                this.state.channel.activeRtcSession = undefined;
            }
        } else {
            if (cleanup) {
                for (const stream of session.videoStreams.values()) {
                    closeStream(stream);
                }
            }
            session.videoStreams.clear();
        }
    }
    /**
     * @param {import("models").RtcSession} session
     */
    removeAudioFromSession(session) {
        closeStream(session.audioStream);
        if (session.audioElement) {
            session.audioElement.pause();
            try {
                session.audioElement.srcObject = undefined;
            } catch {
                // ignore error during remove, the value will be overwritten at next usage anyway
            }
        }
        session.audioStream = undefined;
    }

    /**
     * @param {import("models").RtcSession} session
     * @param {"screen"|"camera"} [videoType]
     * @param {Object} [parm2]
     * @param {boolean} [parm2.addVideo]
     */
    updateActiveSession(session, videoType, { addVideo = false } = {}) {
        const activeRtcSession = this.state.channel.activeRtcSession;
        if (addVideo) {
            if (videoType === "screen") {
                this.state.channel.activeRtcSession = session;
                session.mainVideoStreamType = videoType;
                return;
            }
            if (
                activeRtcSession &&
                session.hasVideo &&
                !session.isMainVideoStreamActive
            ) {
                session.mainVideoStreamType = videoType;
            }
            return;
        }
        if (!activeRtcSession || activeRtcSession.notEq(session)) {
            return;
        }
        if (activeRtcSession.isMainVideoStreamActive) {
            if (videoType === session.mainVideoStreamType) {
                if (videoType === "screen") {
                    session.mainVideoStreamType = "camera";
                } else if (
                    this.actionsStack.includes("camera-on") &&
                    this.actionsStack.includes("share-screen")
                ) {
                    session.mainVideoStreamType = "screen";
                }
            }
        }
    }

    /**
     * @param {import("models").RtcSession} rtcSession
     * @param {Object} [param1]
     * @param {number} [param1.viewCountIncrement=0] negative value to decrement
     */
    updateVideoDownload(rtcSession, { viewCountIncrement = 0 } = {}) {
        rtcSession.videoComponentCount += viewCountIncrement;
        if (!this.state.channel) {
            // out of a call (e.g. delayed timeout firing after `clear()`):
            // nothing to download, and no timeout should be (re)scheduled.
            return;
        }
        const downloadTimeout = this.downloadTimeouts.get(rtcSession.id);
        if (downloadTimeout) {
            this.downloadTimeouts.delete(rtcSession.id);
            browser.clearTimeout(downloadTimeout);
        }
        if (rtcSession.videoComponentCount > 0) {
            this.network?.updateDownload(rtcSession.id, {
                camera: true,
                screen: true,
            });
        } else {
            /**
             * We wait a bit before pausing a download to avoid flickering, if the user stops downloading and starts again
             * soon after, it is not worth pausing the download.
             */
            this.downloadTimeouts.set(
                rtcSession.id,
                browser.setTimeout(() => {
                    this.downloadTimeouts.delete(rtcSession.id);
                    this.network?.updateDownload(rtcSession.id, {
                        camera: false,
                        screen: false,
                    });
                }, 1000),
            );
        }
    }
}

Rtc.register();

export const rtcService = {
    dependencies: [
        "bus_service",
        "discuss.p2p",
        "discuss.pip_service",
        "discuss.ptt_extension",
        "mail.fullscreen",
        "mail.sound_effects",
        "mail.store",
        "legacy_multi_tab",
        "notification",
        "presence",
    ],
    /**
     * @param {import("@web/env").OdooEnv} env
     * @param {import("services").ServiceFactories} services
     */
    start(env, services) {
        const store = env.services["mail.store"];
        const rtc = store.rtc;
        rtc.pipService = services["discuss.pip_service"];
        onChange(rtc.pipService.state, "active", () => {
            const isPipMode = rtc.pipService.state.active;
            if (!isPipMode) {
                rtc.channel?.openChatWindow();
            }
            rtc.state.isPipMode = isPipMode;
            rtc.crossTab?.notifyPipChange(isPipMode);
        });
        rtc.fullscreen = services["mail.fullscreen"];
        onChange(rtc.fullscreen, "id", () => {
            const wasFullscreen = rtc.state.isFullscreen;
            rtc.state.isFullscreen = rtc.fullscreen.id === CALL_FULLSCREEN_ID;
            if (
                rtc.state.screenTrack &&
                rtc.displaySurface !== "browser" &&
                rtc.fullscreen.id === CALL_FULLSCREEN_ID
            ) {
                rtc.showMirroringWarning();
            } else if (!rtc.state.isFullscreen) {
                rtc.removeMirroringWarning?.();
                if (wasFullscreen && rtc.state.screenTrack) {
                    rtc.state.screenTrack.enabled = true;
                }
            }
        });
        browser.navigator.permissions?.query({ name: "microphone" }).then((status) => {
            rtc.microphonePermission = status.state;
            status.onchange = () => (rtc.microphonePermission = status.state);
        });
        browser.navigator.permissions?.query({ name: "camera" }).then((status) => {
            rtc.cameraPermission = status.state;
            status.onchange = () => (rtc.cameraPermission = status.state);
        });
        rtc.p2pService = services["discuss.p2p"];
        rtc.p2pService.acceptOffer = async (id, sequence) => {
            const session = await store["discuss.channel.rtc.session"].getWhenReady(
                Number(id),
            );
            /**
             * We only accept offers for new connections (higher sequence),
             * or offers that renegotiate an existing connection (same sequence).
             */
            return sequence >= session?.sequence;
        };
        services["bus_service"].subscribe(
            "discuss.channel.rtc.session/sfu_hot_swap",
            async ({ serverInfo }) => {
                if (!rtc.localSession) {
                    return;
                }
                if (rtc.serverInfo?.channelUUID === serverInfo.channelUUID) {
                    // we clear peers as inbound p2p connections may still be active
                    rtc.p2pService.removeALlPeers();
                    // no reason to swap if the server is the same, if at some point we want to force a swap
                    // there should be an explicit flag in the event payload.
                    return;
                }
                rtc.serverInfo = serverInfo;
                await rtc._initConnection();
            },
        );
        services["bus_service"].subscribe(
            "discuss.channel.rtc.session/ended",
            ({ sessionId }) => {
                if (rtc.localSession?.id === sessionId) {
                    rtc.notifyServerDisconnect();
                    rtc.endCall();
                }
            },
        );
        services["bus_service"].subscribe("res.users.settings.volumes", (payload) => {
            if (payload) {
                rtc.store.Volume.insert(payload);
            }
        });
        services["bus_service"].subscribe(
            "discuss.channel.rtc.session/update_and_broadcast",
            (payload) => {
                const { data, channelId } = payload;
                /**
                 * If this event comes from the channel of the current call, information is shared in real time
                 * through the peer to peer connection. So we do not use this less accurate broadcast.
                 */
                if (channelId !== rtc.channel?.id) {
                    rtc.store.insert(data);
                }
            },
        );
        /**
         * Attempts to play RTC medias when a user shows signs of presence (interaction with the page) as
         * they cannot be played on windows that have not been interacted with.
         */
        services["presence"].bus.addEventListener(
            "presence",
            () => {
                env.bus.trigger("RTC-SERVICE:PLAY_MEDIA");
            },
            { once: true },
        );
        return rtc;
    },
};

registry.category("services").add("discuss.rtc", rtcService);
