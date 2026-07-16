/** @odoo-module native */
import { Action, ACTION_TAGS } from "@mail/core/common/action";
import { ActionList } from "@mail/core/common/action_list";
import {
    cameraOnAction,
    muteAction,
    quickActionSettings,
    quickVideoSettings,
} from "@mail/discuss/call/common/call_actions";
import { CallPermissionDialog } from "@mail/discuss/call/common/call_permission_dialog";
import { closeStream, onChange } from "@mail/utils/common/misc";
import {
    Component,
    onWillDestroy,
    status,
    useEffect,
    useRef,
    useState,
} from "@odoo/owl";
import { _t } from "@web/core/l10n/translation";
import { useService } from "@web/core/utils/hooks";
/**
 * @typedef {Object} Props
 * @property {Number} [activateCamera]
 * @property {Number} [activateMicrophone]
 * @property {({ microphone?: boolean, camera?: boolean }) => void} [onSettingsChanged]
 * @extends {Component<Props, Env>}
 */
export class CallPreview extends Component {
    static template = "mail.CallPreview";
    static props = ["activateCamera?", "activateMicrophone?", "onSettingsChanged?"];
    static components = { ActionList };

    setup() {
        this.dialog = useService("dialog");
        this.notification = useService("notification");
        this.rtc = useService("discuss.rtc");
        this.store = useService("mail.store");
        this.state = useState({
            audioStream: null,
            blurManager: null,
            // Resolved blurred MediaStream (BlurManager.stream is a Promise); the effect binds
            // this concrete stream, never the pending promise.
            blurStream: null,
            videoStream: null,
        });
        this.audioRef = useRef("audio");
        this.videoRef = useRef("video");
        // Single source of truth for stream -> media-element binding: the <audio>/<video>
        // elements always mirror current stream state, in both directions (bind on enable,
        // clear on disable, swap on blur). Because this is the *only* place srcObject is
        // touched, enable*/disable*/blur mutate reactive state alone and never depend on a
        // ref being mounted -- so the parent-notification contract can never again be gated
        // behind a not-yet-rendered element (the guest-joins-camera-off bug).
        useEffect(
            (videoEl, audioEl, audioStream, videoStream, blurStream) => {
                if (audioEl && audioEl.srcObject !== audioStream) {
                    audioEl.srcObject = audioStream ?? null;
                }
                const desiredVideo = blurStream ?? videoStream ?? null;
                if (videoEl && videoEl.srcObject !== desiredVideo) {
                    videoEl.srcObject = desiredVideo;
                }
            },
            () => [
                this.videoRef.el,
                this.audioRef.el,
                this.state.audioStream,
                this.state.videoStream,
                this.state.blurStream,
            ],
        );
        if (this.hasRtcSupport) {
            onChange(this.rtc, "microphonePermission", () => {
                if (this.rtc.microphonePermission !== "granted") {
                    this.disableMicrophone();
                }
            });
            onChange(this.rtc, "cameraPermission", () => {
                if (this.rtc.cameraPermission !== "granted") {
                    this.disableCamera();
                }
            });
            onChange(this.store.settings, "audioInputDeviceId", () => {
                if (this.state.audioStream) {
                    closeStream(this.state.audioStream);
                    this.enableMicrophone();
                }
            });
            onChange(this.store.settings, "cameraInputDeviceId", () => {
                if (this.state.videoStream) {
                    closeStream(this.state.videoStream);
                    this.enableCamera();
                }
            });
            onChange(this.store.settings, "audioOutputDeviceId", (deviceId) => {
                this.audioRef.el?.setSinkId?.(deviceId).catch(() => {});
            });
            onChange(this.store.settings, "useBlur", () => {
                if (this.store.settings.useBlur) {
                    this.enableBlur();
                } else {
                    this.disableBlur();
                }
            });
            onChange(
                this.store.settings,
                ["edgeBlurAmount", "backgroundBlurAmount"],
                () => {
                    if (this.state.blurManager) {
                        this.state.blurManager.edgeBlur =
                            this.store.settings.edgeBlurAmount;
                        this.state.blurManager.backgroundBlur =
                            this.store.settings.backgroundBlurAmount;
                    }
                },
            );
            onWillDestroy(() => {
                closeStream(this.state.audioStream);
                closeStream(this.state.videoStream);
                // The BlurManager owns a Web Worker, a SelfieSegmentation
                // instance and a canvas.captureStream(); without closing it (and
                // its output stream) here, dismissing the preview with blur on
                // leaks a live worker + capture stream for the tab's lifetime.
                closeStream(this.state.blurStream);
                this.state.blurManager?.close();
            });
            useEffect(
                (activateCamera) => {
                    if (activateCamera > 0 && !this.state.videoStream) {
                        this.enableCamera();
                    }
                },
                () => [this.props.activateCamera],
            );
            useEffect(
                (activateMicrophone) => {
                    if (activateMicrophone > 0 && !this.state.audioStream) {
                        this.enableMicrophone();
                    }
                },
                () => [this.props.activateMicrophone],
            );
        }
    }

    get hasRtcSupport() {
        return Boolean(
            navigator.mediaDevices &&
            navigator.mediaDevices.getUserMedia &&
            window.MediaStream,
        );
    }

    get actions() {
        const cameraOnActionUpdated = {
            ...cameraOnAction,
            name: () =>
                this.state.videoStream ? _t("Stop camera") : _t("Turn camera on"),
            isActive: () => this.state.videoStream,
            onSelected: () => this.toggleCamera(),
            tags: (...args) => {
                const tags = cameraOnAction.tags?.(...args) ?? [];
                if (!args[0].action.isActive) {
                    tags.push(ACTION_TAGS.DANGER);
                }
                return tags;
            },
        };
        const muteActionUpdated = {
            ...muteAction,
            isActive: () => !this.state.audioStream,
            name: ({ action }) => (action.isActive ? _t("Unmute") : _t("Mute")),
            onSelected: () => this.toggleMic(),
        };
        return [
            [
                new Action({
                    id: "toggle-microphone",
                    owner: this,
                    definition: muteActionUpdated,
                    store: this.store,
                }),
                new Action({
                    id: "audio-settings",
                    owner: this,
                    definition: quickActionSettings,
                    store: this.store,
                }),
            ],
            [
                new Action({
                    id: "toggle-camera",
                    owner: this,
                    definition: cameraOnActionUpdated,
                    store: this.store,
                }),
                new Action({
                    id: "video-settings",
                    owner: this,
                    definition: quickVideoSettings,
                    store: this.store,
                }),
            ],
        ];
    }

    /**
     * Acquire a local media stream and publish it. Single acquire routine shared by the
     * microphone and camera paths so the two can never diverge (the divergence is what let the
     * camera path grow a DOM-gated notification the mic path never had). Order is invariant:
     * permission -> getUserMedia -> destroyed guard -> commit state -> notify parent. DOM binding
     * is left entirely to the reactive effect, so the parent is notified regardless of render
     * timing.
     *
     * @param {Object} media
     * @param {"audio"|"video"} media.kind getUserMedia constraint key
     * @param {"microphonePermission"|"cameraPermission"} media.permission
     * @param {MediaTrackConstraints} media.constraints
     * @param {"audioStream"|"videoStream"} media.streamKey `this.state` slot to commit to
     * @param {"microphone"|"camera"} media.setting `onSettingsChanged` flag to raise
     * @returns {Promise<boolean>} whether the stream was acquired and committed
     */
    async acquireMedia({ kind, permission, constraints, streamKey, setting }) {
        if (
            this.rtc[permission] !== "granted" &&
            !(await this.rtc.askForBrowserPermission({ [kind]: true }))
        ) {
            return false;
        }
        let stream;
        try {
            stream = await navigator.mediaDevices.getUserMedia({
                [kind]: constraints,
            });
        } catch {
            // permission may be "granted" while the device is unusable:
            // claimed by another app (NotReadableError) or unplugged since
            // the grant (NotFoundError) — without this it escaped as an
            // unhandled rejection and left the preview state inconsistent
            this.rtc.showMediaUnavailableWarning({
                microphone: kind === "audio",
                camera: kind === "video",
            });
            return false;
        }
        // destroyed check must come first: on a dismissed popup the stream must be closed,
        // not leaked with the device LED on.
        if (status(this) === "destroyed") {
            closeStream(stream);
            return false;
        }
        this.state[streamKey] = stream;
        this.props.onSettingsChanged?.({ [setting]: true });
        return true;
    }

    async enableMicrophone() {
        await this.acquireMedia({
            kind: "audio",
            permission: "microphonePermission",
            constraints: this.store.settings.audioConstraints,
            streamKey: "audioStream",
            setting: "microphone",
        });
    }

    disableMicrophone() {
        closeStream(this.state.audioStream);
        this.state.audioStream = null;
        this.props.onSettingsChanged?.({ microphone: false });
    }

    async toggleMic() {
        if (this.state.audioStream) {
            this.disableMicrophone();
            return;
        }
        if (this.rtc.microphonePermission === "prompt") {
            this.dialog.add(CallPermissionDialog, {
                media: "microphone",
                useMicrophone: () => this.enableMicrophone(),
                useCamera: () => this.enableCamera(),
            });
            return;
        }
        await this.enableMicrophone();
    }

    async enableCamera() {
        const acquired = await this.acquireMedia({
            kind: "video",
            permission: "cameraPermission",
            constraints: this.store.settings.cameraConstraints,
            streamKey: "videoStream",
            setting: "camera",
        });
        if (acquired && this.store.settings.useBlur) {
            await this.enableBlur();
        }
    }

    disableCamera() {
        closeStream(this.state.videoStream);
        this.state.videoStream = null;
        this.state.blurManager?.close();
        this.state.blurManager = undefined;
        this.state.blurStream = null;
        this.props.onSettingsChanged?.({ camera: false });
    }

    async toggleCamera() {
        if (this.state.videoStream) {
            this.disableCamera();
            return;
        }
        if (this.rtc.cameraPermission === "prompt") {
            this.dialog.add(CallPermissionDialog, {
                media: "camera",
                useMicrophone: () => this.enableMicrophone(),
                useCamera: () => this.enableCamera(),
            });
            return;
        }
        await this.enableCamera();
    }

    async enableBlur() {
        this.store.settings.setUseBlur(true);
        if (!this.state.videoStream) {
            return;
        }
        try {
            const manager = await this.rtc.applyBlurEffect(this.state.videoStream);
            // BlurManager.stream is a Promise resolving to the blurred MediaStream; resolve it
            // before committing so the effect binds a concrete stream, not the pending promise.
            const blurStream = await manager.stream;
            if (status(this) === "destroyed") {
                manager.close();
                closeStream(blurStream);
                return;
            }
            // Commit to state only; the reactive effect swaps the <video> to the blurred
            // stream, with no dependence on the element being mounted.
            this.state.blurManager = manager;
            this.state.blurStream = blurStream;
        } catch (_e) {
            this.notification.add(_e.message, { type: "warning" });
            this.disableBlur();
        }
    }

    disableBlur() {
        this.store.settings.setUseBlur(false);
        this.state.blurManager?.close();
        this.state.blurManager = undefined;
        this.state.blurStream = null;
    }

    toggleBlur() {
        if (this.state.blurManager) {
            this.disableBlur();
            return;
        }
        this.enableBlur();
    }
}
