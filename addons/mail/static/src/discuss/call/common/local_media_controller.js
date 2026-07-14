/** @odoo-module native */
import { BlurManager } from "@mail/discuss/call/common/blur_manager";
import { monitorAudio } from "@mail/utils/common/media_monitoring";
import { closeStream } from "@mail/utils/common/misc";
import { browser } from "@web/core/browser/browser";
import { isMobileOS } from "@web/core/browser/feature_detection";
import { _t } from "@web/core/l10n/translation";
import { Mutex } from "@web/core/utils/concurrency";
import { debounce } from "@web/core/utils/timing";

const SCREEN_CONFIG = {
    width: { max: 1920 },
    height: { max: 1080 },
    aspectRatio: 16 / 9,
    frameRate: {
        max: 24,
    },
};

/**
 * Delegate surface the coordinator (Rtc) provides to the media controller.
 * Session state, broadcasting and UI feedback go through these callbacks so
 * the track lifecycle stays headless-testable.
 *
 * @typedef {Object} LocalMediaHooks
 * @property {() => import("models").Settings} getSettings
 * @property {() => import("models").RtcSession|undefined} getLocalSession
 * @property {() => import("models").RtcSession|undefined} getSelfSession
 * @property {(type: string, track: MediaStreamTrack|undefined) => Promise} updateTrackUpload
 *  best-effort upload of one outbound track through the active network
 * @property {(isMute: boolean) => Promise} setMute
 * @property {(media: {microphone?: boolean, camera?: boolean, screen?: boolean}) => void} onMediaUnavailable
 * @property {(type: string, options: Object|boolean) => Promise} toggleVideo
 *  used by the video track "ended" listeners
 * @property {(soundName: string) => void} playSound
 * @property {(text: string) => void} notify warning notification
 * @property {(isTalking: boolean) => void} setTalking
 * @property {() => Promise} refreshMicAudioStatus applies the mic track state
 *  and broadcasts the new session info
 */

/**
 * Owns every local MediaStreamTrack of a call: microphone, camera and screen
 * tracks, the mic/screen audio mixing AudioContext, the blur pipeline and the
 * voice activation monitor. Every track stop/close belongs here; the
 * coordinator only calls the narrow methods below.
 *
 * The tracks/streams themselves live in the shared reactive `state` (they are
 * rendered by call components); the controller is their single writer.
 */
export class LocalMediaController {
    /** @type {AudioContext} AudioContext used to mix screen and mic audio */
    audioContext;
    /** @type {BlurManager|undefined} */
    blurManager;
    /**
     * Serializes `updateAudioTrack` runs: concurrent runs would race on the
     * shared mix AudioContext (double close/create, context leak).
     */
    _audioTrackMutex = new Mutex();

    /**
     * @param {Object} param0
     * @param {Object} param0.state shared reactive call state; the controller
     *  owns the track/stream/send slots
     * @param {LocalMediaHooks} param0.hooks
     */
    constructor({ state, hooks }) {
        this.state = state;
        this.hooks = hooks;
        this.linkVoiceActivationDebounce = debounce(this.linkVoiceActivation, 500);
    }

    /**
     * Applies blur effect to a video stream using BlurManager.
     *
     * @param {MediaStream} videoStream - input video stream.
     * @returns {Promise<BlurManager>} - BlurManager instance.
     */
    async applyBlurEffect(videoStream) {
        const settings = this.hooks.getSettings();
        return new BlurManager(videoStream, {
            backgroundBlur: settings.backgroundBlurAmount,
            edgeBlur: settings.edgeBlurAmount,
        });
    }

    /**
     * Sets the enabled property of the local microphone audio track based on
     * the current session state.
     */
    applyMicState() {
        const session = this.hooks.getLocalSession();
        this.state.micAudioTrack.enabled = !session.isMute && session.isTalking;
    }

    /**
     * @param {String} type 'camera' or 'screen'
     * @param {Object} [param1] options
     * @param {Boolean} [param1.activateVideo=false] options
     * @param {Env} [param1.env]
     * @param {Boolean} [param1.refreshStream] whether we are requesting a new stream
     */
    async setVideo(track, type, options) {
        const settings = this.hooks.getSettings();
        let activateVideo;
        let env;
        if (typeof options === "boolean") {
            activateVideo = options ?? false;
        } else {
            activateVideo = options?.activateVideo ?? false;
            env = options?.env;
        }
        const stopVideo = async () => {
            if (track) {
                track.stop();
            }
            switch (type) {
                case "camera": {
                    this.state.cameraTrack = undefined;
                    closeStream(this.state.sourceCameraStream);
                    this.state.sourceCameraStream = null;
                    break;
                }
                case "screen": {
                    this.state.screenTrack = undefined;
                    // Also stop the captured tab/system audio: leaving it live
                    // kept the shared audio in the outgoing mix after the user
                    // stopped screen-sharing (other participants kept hearing
                    // it). Rebuild the audio mix without it.
                    this.state.screenAudioTrack?.stop();
                    this.state.screenAudioTrack = undefined;
                    closeStream(this.state.sourceScreenStream);
                    this.state.sourceScreenStream = null;
                    await this.updateAudioTrack();
                    break;
                }
            }
        };
        if (!activateVideo) {
            if (type === "screen") {
                this.hooks.playSound("screen-sharing");
            }
            if (type === "camera" && this.blurManager) {
                this.blurManager.close();
                this.blurManager = undefined;
            }
            await stopVideo();
            return;
        }
        let sourceStream;
        const sourceWindow = env?.pipWindow ?? browser;
        try {
            if (type === "camera") {
                if (this.state.sourceCameraStream && !options?.refreshStream) {
                    sourceStream = this.state.sourceCameraStream;
                } else {
                    closeStream(this.state.sourceCameraStream);
                    sourceStream =
                        await sourceWindow.navigator.mediaDevices.getUserMedia({
                            video: settings.cameraConstraints,
                        });
                }
            }
            if (type === "screen") {
                if (this.state.sourceScreenStream) {
                    sourceStream = this.state.sourceScreenStream;
                } else {
                    sourceStream =
                        await sourceWindow.navigator.mediaDevices.getDisplayMedia({
                            video: SCREEN_CONFIG,
                            audio: true,
                        });
                }
                this.hooks.playSound("screen-sharing");
            }
        } catch {
            this.hooks.onMediaUnavailable({
                camera: type === "camera",
                screen: type === "screen",
            });
            await stopVideo();
            return;
        }
        if (!this.hooks.getSelfSession()) {
            closeStream(sourceStream);
            return;
        }
        let outputTrack = sourceStream ? sourceStream.getVideoTracks()[0] : undefined;
        const screenAudioTrack = sourceStream
            ? sourceStream.getAudioTracks()[0]
            : undefined;
        if (outputTrack) {
            outputTrack.addEventListener("ended", async () => {
                await this.hooks.toggleVideo(type, { force: false });
            });
            if (type === "camera" && isMobileOS()) {
                const trackSettings = outputTrack.getSettings();
                if (trackSettings?.facingMode) {
                    settings.cameraFacingMode = trackSettings.facingMode;
                } else if (!settings.cameraFacingMode) {
                    settings.cameraFacingMode = "user";
                }
            }
        }
        if (settings.useBlur && type === "camera") {
            this.blurManager?.close();
            this.blurManager = undefined;
            try {
                this.blurManager = await this.applyBlurEffect(sourceStream);
                const blurredStream = await this.blurManager.stream;
                outputTrack = blurredStream.getVideoTracks()[0];
            } catch (_e) {
                this.hooks.notify(_e.message);
                settings.setUseBlur(false);
                outputTrack = sourceStream.getVideoTracks()[0];
            }
        } else if (!settings.useBlur && type === "camera") {
            this.blurManager?.close();
            this.blurManager = undefined;
        }
        switch (type) {
            case "camera": {
                Object.assign(this.state, {
                    sourceCameraStream: sourceStream,
                    cameraTrack: outputTrack,
                    sendCamera: Boolean(outputTrack),
                    isCameraSourceExternal: Boolean(sourceStream) && env?.pipWindow,
                });
                break;
            }
            case "screen": {
                Object.assign(this.state, {
                    sourceScreenStream: sourceStream,
                    screenTrack: outputTrack,
                    screenAudioTrack: screenAudioTrack,
                    sendScreen: Boolean(outputTrack),
                    isScreenSourceExternal: Boolean(sourceStream) && env?.pipWindow,
                });
                break;
            }
        }
        if (this.state.screenAudioTrack) {
            await this.updateAudioTrack();
        }
    }

    /**
     * Rebuilds `state.audioTrack` from the current mic/screen audio tracks
     * (mixing them when both are present) and updates the outbound upload
     * accordingly. Serialized behind a mutex: concurrent runs would race on
     * the shared mix AudioContext (double close/create, context leak).
     */
    updateAudioTrack() {
        return this._audioTrackMutex.exec(async () => {
            const { micAudioTrack, screenAudioTrack } = this.state;
            if (micAudioTrack && screenAudioTrack) {
                await this.audioContext?.close();
                this.audioContext = new AudioContext();
                const micSource = this.audioContext.createMediaStreamSource(
                    new MediaStream([micAudioTrack]),
                );
                const screenSource = this.audioContext.createMediaStreamSource(
                    new MediaStream([screenAudioTrack]),
                );
                const destination = this.audioContext.createMediaStreamDestination();
                micSource.connect(destination);
                screenSource.connect(destination);
                this.state.audioTrack = destination.stream.getAudioTracks()[0];
            } else {
                // At most one source remains: no mixing needed. Tear down the
                // mix AudioContext (browsers cap concurrent contexts, so
                // leaking one per screen-share toggle eventually breaks audio
                // for the rest of the call) and stop the now-unused mixed
                // destination track.
                if (this.audioContext) {
                    await this.audioContext.close();
                    this.audioContext = undefined;
                }
                const previousTrack = this.state.audioTrack;
                this.state.audioTrack = micAudioTrack ?? screenAudioTrack;
                if (previousTrack && previousTrack !== this.state.audioTrack) {
                    previousTrack.stop();
                }
            }
            // always resynchronize the senders, including with no track at
            // all: they must not keep streaming an ended track.
            await this.hooks.updateTrackUpload("audio", this.state.audioTrack);
        });
    }

    async resetMicAudioTrack({ force = false }) {
        this.state.micAudioTrack?.stop();
        this.state.micAudioTrack = undefined;
        if (
            this.state.audioTrack &&
            this.state.audioTrack !== this.state.screenAudioTrack
        ) {
            // `audioTrack` is then the mic track itself or a mixed
            // (mic + screen) destination track, both owned by this service
            // and safe to stop. When screen-sharing without a mic track,
            // `audioTrack` IS the live screen-capture audio track: stopping
            // it would irreversibly end the shared tab/system audio for all
            // participants (a MediaStreamTrack cannot be restarted).
            this.state.audioTrack.stop();
        }
        this.state.audioTrack = undefined;
        if (!this.state.channel) {
            return;
        }
        if (this.hooks.getLocalSession()) {
            await this.hooks.setMute(true);
        }
        if (force) {
            let micAudioTrack;
            try {
                const audioStream = await browser.navigator.mediaDevices.getUserMedia({
                    audio: this.hooks.getSettings().audioConstraints,
                });
                micAudioTrack = audioStream.getAudioTracks()[0];
                if (this.hooks.getLocalSession()) {
                    await this.hooks.setMute(false);
                }
            } catch {
                this.hooks.onMediaUnavailable({ microphone: true });
                // still rebuild the outgoing audio (the screen audio may
                // remain) so the senders do not keep an ended track.
                await this.updateAudioTrack();
                return;
            }
            if (!this.hooks.getLocalSession()) {
                // The getUserMedia promise could resolve when the call is ended
                // in which case the track is no longer relevant.
                micAudioTrack.stop();
                return;
            }
            micAudioTrack.addEventListener("ended", async () => {
                // this mostly happens when the user retracts microphone permission.
                await this.resetMicAudioTrack({ force: false });
                await this.hooks.setMute(true);
            });
            const session = this.hooks.getLocalSession();
            micAudioTrack.enabled = !session.isMute && session.isTalking;
            this.state.micAudioTrack = micAudioTrack;
            this.linkVoiceActivationDebounce();
        }
        await this.updateAudioTrack();
    }

    /**
     * Updates the way broadcast of the local audio track is handled,
     * attaches an audio monitor for voice activation if necessary.
     */
    async linkVoiceActivation() {
        this.state.disconnectAudioMonitor?.();
        const session = this.hooks.getLocalSession();
        if (!session) {
            return;
        }
        const settings = this.hooks.getSettings();
        if (
            settings.use_push_to_talk ||
            !this.state.channel ||
            !this.state.micAudioTrack
        ) {
            session.isTalking = false;
            await this.hooks.refreshMicAudioStatus();
            return;
        }
        try {
            this.state.disconnectAudioMonitor = await monitorAudio(
                this.state.micAudioTrack,
                {
                    onThreshold: async (isAboveThreshold) => {
                        this.hooks.setTalking(isAboveThreshold);
                    },
                    volumeThreshold: settings.voiceActivationThreshold,
                },
            );
        } catch {
            /**
             * The browser is probably missing audioContext,
             * in that case, voice activation is not enabled
             * and the microphone is always 'on'.
             */
            this.hooks.notify(_t("Your browser does not support voice activation"));
            session.isTalking = true;
        }
        await this.hooks.refreshMicAudioStatus();
    }

    /**
     * Stops and releases every local media resource and resets the shared
     * state slots this controller owns.
     */
    dispose() {
        this.state.disconnectAudioMonitor?.();
        this.state.micAudioTrack?.stop();
        this.state.screenAudioTrack?.stop();
        this.state.audioTrack?.stop();
        this.state.cameraTrack?.stop();
        this.state.screenTrack?.stop();
        closeStream(this.state.sourceCameraStream);
        this.state.sourceCameraStream = null;
        closeStream(this.state.sourceScreenStream);
        this.state.sourceScreenStream = null;
        this.audioContext?.close();
        this.audioContext = undefined;
        if (this.blurManager) {
            this.blurManager.close();
            this.blurManager = undefined;
        }
        Object.assign(this.state, {
            disconnectAudioMonitor: undefined,
            cameraTrack: undefined,
            screenTrack: undefined,
            screenAudioTrack: undefined,
            micAudioTrack: undefined,
            audioTrack: undefined,
            sendCamera: false,
            sendScreen: false,
        });
    }
}
