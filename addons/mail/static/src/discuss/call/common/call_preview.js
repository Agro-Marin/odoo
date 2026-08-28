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
import { useOnChange } from "@mail/utils/common/hooks";
import { closeStream } from "@mail/utils/common/misc";
import {
    Component,
    onWillDestroy,
    status,
    useEffect,
    useRef,
    useState,
} from "@odoo/owl";
import { _t } from "@web/core/translation";
import { useService } from "@web/core/utils/hooks";
/**
 * @typedef {Object} Props
 * @property {Number} [activateCamera]
 * @property {Number} [activateMicrophone]
 * @property {({ microphone?: boolean, camera?: boolean }) => void} [onSettingsChanged]
 * @extends {Component<Props, import("@web/env").OdooEnv>}
 */
export class CallPreview extends Component {
    static template = "mail.CallPreview";
    static props = ["activateCamera?", "activateMicrophone?", "onSettingsChanged?"];
    static components = { ActionList };

    _setupServicesAndRefs() {
        this.dialog = useService("dialog");
        this.notification = useService("notification");
        this.rtc = useService("discuss.rtc");
        this.store = useService("mail.store");
        this.state = useState({
            audioStream: null,
            blurManager: null,
            blurStream: null,
            videoStream: null,
        });
        this.audioRef = useRef("audio");
        this.videoRef = useRef("video");
    }
    _setupPreviewEffect() {
        useEffect(
            /**
             * @param {HTMLVideoElement|null} videoEl
             * @param {HTMLAudioElement|null} audioEl
             * @param {MediaStream|undefined} audioStream
             * @param {MediaStream|undefined} videoStream
             * @param {MediaStream|undefined} blurStream
             */
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
    }
    _setupRtcPreview() {
        if (this.hasRtcSupport) {
            useOnChange(this.rtc, "microphonePermission", () => {
                if (this.rtc.microphonePermission !== "granted") {
                    this.disableMicrophone();
                }
            });
            useOnChange(this.rtc, "cameraPermission", () => {
                if (this.rtc.cameraPermission !== "granted") {
                    this.disableCamera();
                }
            });
            useOnChange(this.store.settings, "audioInputDeviceId", () => {
                if (this.state.audioStream) {
                    closeStream(this.state.audioStream);
                    this.enableMicrophone();
                }
            });
            useOnChange(this.store.settings, "cameraInputDeviceId", () => {
                if (this.state.videoStream) {
                    closeStream(this.state.videoStream);
                    this.enableCamera();
                }
            });
            useOnChange(this.store.settings, "audioOutputDeviceId", () => {
                this.audioRef.el
                    ?.setSinkId?.(this.store.settings.audioOutputDeviceId)
                    .catch(() => {});
            });
            useOnChange(this.store.settings, "useBlur", () => {
                if (this.store.settings.useBlur) {
                    this.enableBlur();
                } else {
                    this.disableBlur();
                }
            });
            useOnChange(
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
                closeStream(this.state.blurStream);
                this.state.blurManager?.close();
            });
            useEffect(
                /** @param {number} activateCamera */
                (activateCamera) => {
                    if (activateCamera > 0 && !this.state.videoStream) {
                        this.enableCamera();
                    }
                },
                () => [this.props.activateCamera],
            );
            useEffect(
                /** @param {number} activateMicrophone */
                (activateMicrophone) => {
                    if (activateMicrophone > 0 && !this.state.audioStream) {
                        this.enableMicrophone();
                    }
                },
                () => [this.props.activateMicrophone],
            );
        }
    }
    setup() {
        this._setupServicesAndRefs();
        this._setupPreviewEffect();
        this._setupRtcPreview();
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
            /** @param {...import("./call_actions").ActionParams} args */
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
            /** @param {import("./call_actions").ActionParams} params */
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
     * @param {Object} media
     * @param {"audio"|"video"} media.kind
     * @param {"microphonePermission"|"cameraPermission"} media.permission
     * @param {MediaTrackConstraints} media.constraints
     * @param {"audioStream"|"videoStream"} media.streamKey
     * @param {"microphone"|"camera"} media.setting
     * @returns {Promise<boolean>}
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
            this.rtc.showMediaUnavailableWarning({
                microphone: kind === "audio",
                camera: kind === "video",
            });
            return false;
        }
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
            const blurStream = await manager.stream;
            if (status(this) === "destroyed") {
                manager.close();
                closeStream(blurStream);
                return;
            }
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
