/** @odoo-module native */
import { BlurManager } from "@mail/discuss/call/common/blur_manager";
import { monitorAudio } from "@mail/utils/common/media_monitoring";
import { closeStream } from "@mail/utils/common/misc";
import { browser } from "@web/core/browser/browser";
import { isMobileOS } from "@web/core/browser/feature_detection";
import { _t } from "@web/core/translation";
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
 * @typedef {Object} LocalMediaHooks
 * @property {() => import("models").Settings} getSettings
 * @property {() => import("models").RtcSession|undefined} getLocalSession
 * @property {() => import("models").RtcSession|undefined} getSelfSession
 * @property {(type: string, track: MediaStreamTrack|undefined) => Promise} updateTrackUpload
 * @property {(isMute: boolean) => Promise} setMute
 * @property {(media: {microphone?: boolean, camera?: boolean, screen?: boolean}) => void} onMediaUnavailable
 * @property {(type: string, options: Object|boolean) => Promise} toggleVideo
 * @property {(soundName: string) => void} playSound
 * @property {(text: string) => void} notify
 * @property {(isTalking: boolean) => void} setTalking
 * @property {() => Promise} refreshMicAudioStatus
 */
export class LocalMediaController {
    /** @type {AudioContext} */
    audioContext;
    /** @type {BlurManager|undefined} */
    blurManager;
    _audioTrackMutex = new Mutex();
    _videoMutexes = { camera: new Mutex(), screen: new Mutex() };
    _voiceActivationMutex = new Mutex();

    /**
     * @param {Object} param0
     * @param {import("@mail/discuss/call/common/rtc_service").RtcCallState} param0.state
     * @param {LocalMediaHooks} param0.hooks
     */
    constructor({ state, hooks }) {
        this.state = state;
        this.hooks = hooks;
        this.linkVoiceActivationDebounce = debounce(this.linkVoiceActivation, 500);
    }

    /**
     * @param {MediaStream} videoStream
     * @returns {Promise<BlurManager>}
     */
    async applyBlurEffect(videoStream) {
        const settings = this.hooks.getSettings();
        return new BlurManager(videoStream, {
            backgroundBlur: settings.backgroundBlurAmount,
            edgeBlur: settings.edgeBlurAmount,
        });
    }

    applyMicState() {
        const session = this.hooks.getLocalSession();
        this.state.micAudioTrack.enabled = !session.isMute && session.isTalking;
    }

    /**
     * @param {MediaStreamTrack|undefined} track
     * @param {"camera"|"screen"} type
     * @param {SetVideoOptions|boolean} [options]
     */
    async setVideo(track, type, options) {
        return this._videoMutexes[type].exec(() =>
            this._setVideo(track, type, options),
        );
    }

    /**
     * @typedef {Object} SetVideoOptions
     * @property {boolean} [activateVideo=false]
     * @property {import("@web/env").OdooEnv} [env]
     * @property {boolean} [refreshStream]
     */
    /**
     * @param {MediaStreamTrack|undefined} track
     * @param {"camera"|"screen"} type
     * @param {SetVideoOptions|boolean} [options]
     */
    async _setVideo(track, type, options) {
        const settings = this.hooks.getSettings();
        let activateVideo;
        let env;
        let refreshStream;
        if (typeof options === "boolean") {
            activateVideo = options ?? false;
        } else {
            activateVideo = options?.activateVideo ?? false;
            env = options?.env;
            refreshStream = options?.refreshStream;
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
                if (this.state.sourceCameraStream && !refreshStream) {
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
                const blurredStream = await Promise.race([
                    this.blurManager.stream,
                    new Promise((_, reject) =>
                        browser.setTimeout(
                            () => reject(new Error(_t("Blur is unavailable"))),
                            10_000,
                        ),
                    ),
                ]);
                outputTrack = blurredStream.getVideoTracks()[0];
            } catch (_e) {
                this.hooks.notify(_e.message);
                settings.setUseBlur(false);
                this.blurManager?.close();
                this.blurManager = undefined;
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
                });
                break;
            }
            case "screen": {
                Object.assign(this.state, {
                    sourceScreenStream: sourceStream,
                    screenTrack: outputTrack,
                    screenAudioTrack: screenAudioTrack,
                    sendScreen: Boolean(outputTrack),
                });
                break;
            }
        }
        if (this.state.screenAudioTrack) {
            await this.updateAudioTrack();
        }
    }

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
            await this.hooks.updateTrackUpload("audio", this.state.audioTrack);
        });
    }

    /**
     * @param {Object} [options]
     * @param {boolean} [options.force]
     * @param {boolean} [options.unmute]
     */
    async resetMicAudioTrack({ force = false, unmute = true }) {
        const wasMuted = Boolean(this.hooks.getLocalSession()?.is_muted);
        this.state.micAudioTrack?.stop();
        this.state.micAudioTrack = undefined;
        if (
            this.state.audioTrack &&
            this.state.audioTrack !== this.state.screenAudioTrack
        ) {
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
                    await this.hooks.setMute(unmute ? false : wasMuted);
                }
            } catch {
                this.hooks.onMediaUnavailable({ microphone: true });
                await this.updateAudioTrack();
                return;
            }
            if (!this.hooks.getLocalSession()) {
                micAudioTrack.stop();
                return;
            }
            micAudioTrack.addEventListener("ended", async () => {
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

    async linkVoiceActivation() {
        return this._voiceActivationMutex.exec(async () => {
            this.state.disconnectAudioMonitor?.();
            const session = this.hooks.getLocalSession();
            if (!session) {
                return;
            }
            const settings = this.hooks.getSettings();
            const micAudioTrack = this.state.micAudioTrack;
            if (settings.use_push_to_talk || !this.state.channel || !micAudioTrack) {
                session.isTalking = false;
                await this.hooks.refreshMicAudioStatus();
                return;
            }
            try {
                const disconnect = await monitorAudio(micAudioTrack, {
                    /** @param {boolean} isAboveThreshold */
                    onThreshold: async (isAboveThreshold) => {
                        this.hooks.setTalking(isAboveThreshold);
                    },
                    volumeThreshold: settings.voiceActivationThreshold,
                });
                if (this.state.micAudioTrack !== micAudioTrack) {
                    disconnect?.();
                    return;
                }
                this.state.disconnectAudioMonitor = disconnect;
            } catch {
                this.hooks.notify(_t("Your browser does not support voice activation"));
                session.isTalking = true;
            }
            await this.hooks.refreshMicAudioStatus();
        });
    }

    dispose() {
        this.linkVoiceActivationDebounce?.cancel?.();
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
