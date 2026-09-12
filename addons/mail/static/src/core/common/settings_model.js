// @ts-check
/** @odoo-module native */
import {
    onLocalStorageChange,
    readLocalStorageItem,
    removeLocalStorageItem,
    setLocalStorageItem,
} from "@mail/utils/common/local_storage";
import { hasHardwareAcceleration } from "@mail/utils/common/misc";
import { browser } from "@web/core/browser/browser";
import { makeLogger } from "@web/core/debug/debug_logger";
import { luxon } from "@web/core/l10n/luxon";
import { rpc } from "@web/core/network";
import { _t } from "@web/core/translation";
import { debounce } from "@web/core/utils/timing";

import { fields, Record } from "./record.js";

const log = makeLogger("mail.settings");
export const MESSAGE_SOUND = "mail.user_setting.message_sound";
export const USE_BLUR_LS = "mail_user_setting_use_blur";
const DISABLE_CALL_AUTO_FOCUS_LS = "mail_user_setting_disable_call_auto_focus";

export class Settings extends Record {
    /** @type {number} */
    id;
    /** @type {() => void} */
    _stopDeviceIdsWatch;

    /**
     * @template {typeof Record} T
     * @this {T}
     * @param {import("@mail/model/record").RecordData} data
     * @param {import("@mail/model/record").RecordData} ids
     * @returns {InstanceType<T>}
     */
    static new(data, ids) {
        /** @type {import("models").Settings} */
        const record = /** @type {import("models").Settings} */ (
            /** @type {unknown} */ (super.new(data, ids))
        );
        record._stopDeviceIdsWatch = record._watchDeviceIdsAcrossTabs();
        return /** @type {InstanceType<T>} */ (/** @type {unknown} */ (record));
    }

    setup() {
        super.setup();
        this.saveVoiceThresholdDebounce = debounce(() => {
            browser.localStorage.setItem(
                "mail_user_setting_voice_threshold",
                this.voiceActivationThreshold.toString(),
            );
        }, 2000);
        const canvasContext = document.createElement("canvas").getContext("2d");
        this.hasCanvasFilterSupport =
            Boolean(canvasContext) && typeof canvasContext.filter !== "undefined";
        this._loadLocalSettings();
        log.lifecycle("setup", () => ({
            id: this.id,
            hasCanvasFilterSupport: this.hasCanvasFilterSupport,
        }));
    }

    delete() {
        log.lifecycle("delete", () => ({
            id: this.id,
            pendingVolumeSaves: this.volumeSettingsTimeouts.size,
        }));
        this._stopDeviceIdsWatch();
        for (const timeoutId of this.volumeSettingsTimeouts.values()) {
            browser.clearTimeout(timeoutId);
        }
        this.volumeSettingsTimeouts.clear();
        browser.clearTimeout(this.globalSettingsTimeout);
        this.saveVoiceThresholdDebounce.cancel();
        super.delete();
    }

    /** @type {"mentions"|"all"|"no_notif"|false} */
    channel_notifications = fields.Attr("mentions", {
        /** @this {import("models").Settings} */
        compute() {
            return this.channel_notifications === false
                ? "mentions"
                : this.channel_notifications;
        },
    });
    messageSound = fields.Attr(true, {
        /** @this {import("models").Settings} */
        compute() {
            return readLocalStorageItem(this.store, MESSAGE_SOUND) !== "false";
        },
    });
    useCallAutoFocus = fields.Attr(true, {
        /** @this {import("models").Settings} */
        compute() {
            return !readLocalStorageItem(this.store, DISABLE_CALL_AUTO_FOCUS_LS);
        },
        /** @this {import("models").Settings} */
        onUpdate() {
            if (this.useCallAutoFocus) {
                removeLocalStorageItem(this.store, DISABLE_CALL_AUTO_FOCUS_LS);
                return;
            }
            setLocalStorageItem(this.store, DISABLE_CALL_AUTO_FOCUS_LS, "true");
        },
    });

    audioInputDeviceId = "";
    audioOutputDeviceId = "";
    cameraInputDeviceId = "";
    use_push_to_talk = false;
    voice_active_duration = 200;
    volumes = fields.Many("Volume");
    /** @type {Map<string, number>} */
    volumeSettingsTimeouts = new Map();
    voiceActivationThreshold = 0.05;
    isRegisteringKey = false;
    /** @type {string|undefined} */
    push_to_talk_key;

    backgroundBlurAmount = 10;
    edgeBlurAmount = 10;
    showOnlyVideo = false;
    useBlur = fields.Attr(false, {
        /** @this {import("models").Settings} */
        compute() {
            return readLocalStorageItem(this.store, USE_BLUR_LS) === "true";
        },
    });
    blurPerformanceWarning = fields.Attr(false, {
        /** @this {import("models").Settings} */
        compute() {
            const rtc = this.store.rtc;
            if (!rtc || !this.useBlur) {
                return false;
            }
            return this.useBlur && rtc.state?.cameraTrack && !hasHardwareAcceleration();
        },
    });
    /** @type {"user"|"environment"|undefined} */
    cameraFacingMode = undefined;

    logRtc = false;
    /** @returns {Object} */
    get audioConstraints() {
        const constraints = {
            echoCancellation: true,
            noiseSuppression: true,
        };
        if (this.audioInputDeviceId) {
            constraints.deviceId = this.audioInputDeviceId;
        }
        return constraints;
    }

    get cameraConstraints() {
        const constraints = {
            width: 1280,
        };
        if (this.cameraFacingMode) {
            constraints.facingMode = this.cameraFacingMode;
        } else if (this.cameraInputDeviceId) {
            constraints.deviceId = this.cameraInputDeviceId;
        }
        return constraints;
    }

    get NOTIFICATIONS() {
        return [
            {
                label: "all",
                name: _t("All Messages"),
            },
            {
                label: "mentions",
                name: _t("Mentions Only"),
            },
            {
                label: "no_notif",
                name: _t("Nothing"),
            },
        ];
    }

    get MUTES() {
        return [
            {
                label: "15_mins",
                value: 15,
                name: _t("For 15 minutes"),
            },
            {
                label: "1_hour",
                value: 60,
                name: _t("For 1 hour"),
            },
            {
                label: "3_hours",
                value: 180,
                name: _t("For 3 hours"),
            },
            {
                label: "8_hours",
                value: 480,
                name: _t("For 8 hours"),
            },
            {
                label: "24_hours",
                value: 1440,
                name: _t("For 24 hours"),
            },
            {
                label: "forever",
                value: -1,
                name: _t("Until I turn it back on"),
            },
        ];
    }

    /** @param {boolean} newValue */
    setUseBlur(newValue) {
        log.logic("setUseBlur", () => ({ newValue }));
        if (newValue) {
            setLocalStorageItem(this.store, USE_BLUR_LS, "true");
        } else {
            removeLocalStorageItem(this.store, USE_BLUR_LS);
        }
    }

    /**
     * @param {luxon.DateTime|undefined} dt
     * @returns {string|undefined}
     */
    getMuteUntilText(dt) {
        if (dt) {
            return dt.year <= luxon.DateTime.now().year + 2
                ? _t(`Until %s`, dt.toLocaleString(luxon.DateTime.DATETIME_MED))
                : _t("Until I turn it back on");
        }
        return undefined;
    }

    /**
     * @param {string} custom_notifications
     * @param {import("models").Thread} thread
     */
    async setCustomNotifications(custom_notifications, thread = undefined) {
        log.logic("setCustomNotifications", () => ({
            custom_notifications,
            thread: thread?.localId,
        }));
        return rpc("/discuss/settings/custom_notifications", {
            custom_notifications:
                !thread && custom_notifications === "mentions"
                    ? false
                    : custom_notifications,
            channel_id: thread?.id,
        });
    }

    /**
     * @param {integer|false} minutes
     * @param {import("models").Thread} thread
     */
    async setMuteDuration(minutes, thread = undefined) {
        log.logic("setMuteDuration", () => ({ minutes, thread: thread?.localId }));
        return rpc("/discuss/settings/mute", {
            minutes,
            channel_id: thread?.id,
        });
    }

    /** @param {String} audioInputDeviceId */
    async setAudioInputDevice(audioInputDeviceId) {
        log.logic("setAudioInputDevice", () => ({ audioInputDeviceId }));
        this.audioInputDeviceId = audioInputDeviceId;
        browser.localStorage.setItem(
            "mail_user_setting_audio_input_device_id",
            audioInputDeviceId,
        );
    }
    /** @param {String} audioOutputDeviceId */
    async setAudioOutputDevice(audioOutputDeviceId) {
        log.logic("setAudioOutputDevice", () => ({ audioOutputDeviceId }));
        this.audioOutputDeviceId = audioOutputDeviceId;
        browser.localStorage.setItem(
            "mail_user_setting_audio_output_device_id",
            audioOutputDeviceId,
        );
    }
    /** @param {String} cameraInputDeviceId */
    async setCameraInputDevice(cameraInputDeviceId) {
        log.logic("setCameraInputDevice", () => ({ cameraInputDeviceId }));
        this.cameraFacingMode = undefined;
        this.cameraInputDeviceId = cameraInputDeviceId;
        browser.localStorage.setItem(
            "mail_user_setting_camera_input_device_id",
            cameraInputDeviceId,
        );
    }
    /** @param {string} value */
    setDelayValue(value) {
        log.logic("setDelayValue", () => ({ value }));
        this.voice_active_duration = parseInt(value, 10);
        this._saveSettings();
    }
    /** @param {KeyboardEvent} ev */
    async setPushToTalkKey(ev) {
        const nonElligibleKeys = new Set(["Shift", "Control", "Alt", "Meta"]);
        let pushToTalkKey = `${ev.shiftKey || ""}.${ev.ctrlKey || ev.metaKey || ""}.${
            ev.altKey || ""
        }`;
        if (!nonElligibleKeys.has(ev.key)) {
            pushToTalkKey += `.${ev.key === " " ? "Space" : ev.key}`;
        }
        log.logic("setPushToTalkKey", () => ({ pushToTalkKey }));
        this.push_to_talk_key = pushToTalkKey;
        this._saveSettings();
    }
    /**
     * @param {Object} param0
     * @param {number} [param0.partnerId]
     * @param {number} [param0.guestId]
     * @param {number} param0.volume
     */
    async saveVolumeSetting({ partnerId, guestId, volume }) {
        if (!this.store.self_partner) {
            return;
        }
        const key = `${partnerId}_${guestId}`;
        if (this.volumeSettingsTimeouts.get(key)) {
            browser.clearTimeout(this.volumeSettingsTimeouts.get(key));
        }
        this.volumeSettingsTimeouts.set(
            key,
            browser.setTimeout(
                this._onSaveVolumeSettingTimeout.bind(this, {
                    key,
                    partnerId,
                    guestId,
                    volume,
                }),
                5000,
            ),
        );
    }
    /** @param {number} voiceActivationThreshold */
    setThresholdValue(voiceActivationThreshold) {
        this.voiceActivationThreshold = voiceActivationThreshold;
        this.saveVoiceThresholdDebounce();
    }

    /**
     * @param {Object} shortcut
     * @param {boolean|string} [shortcut.shiftKey]
     * @param {boolean|string} [shortcut.ctrlKey]
     * @param {boolean|string} [shortcut.altKey]
     * @param {string|false} [shortcut.key]
     * @returns {Set<string>}
     */
    getKeySet({ shiftKey, ctrlKey, altKey, key }) {
        const keys = new Set();
        if (key) {
            keys.add(key === "Meta" ? "Alt" : key);
        }
        if (shiftKey) {
            keys.add("Shift");
        }
        if (ctrlKey) {
            keys.add("Control");
        }
        if (altKey) {
            keys.add("Alt");
        }
        return keys;
    }

    /** @param {KeyboardEvent} ev */
    isPushToTalkKey(ev) {
        if (!this.use_push_to_talk || !this.push_to_talk_key) {
            return false;
        }
        const [shiftKey, ctrlKey, altKey, key] = this.push_to_talk_key.split(".");
        const settingsKeySet = this.getKeySet({ shiftKey, ctrlKey, altKey, key });
        const eventKeySet = this.getKeySet({
            shiftKey: ev.shiftKey,
            ctrlKey: ev.ctrlKey,
            altKey: ev.altKey,
            key: ev.key,
        });
        if (ev.type === "keydown") {
            return [...settingsKeySet].every((key) => eventKeySet.has(key));
        }
        return settingsKeySet.has(ev.key === "Meta" ? "Alt" : ev.key);
    }
    pushToTalkKeyFormat() {
        if (!this.push_to_talk_key) {
            return;
        }
        const [shiftKey, ctrlKey, altKey, key] = this.push_to_talk_key.split(".");
        return {
            shiftKey: !!shiftKey,
            ctrlKey: !!ctrlKey,
            altKey: !!altKey,
            key: key || false,
        };
    }
    /** @param {boolean} value */
    setPushToTalk(value) {
        log.logic("setPushToTalk", () => ({ value }));
        this.use_push_to_talk = value;
        this._saveSettings();
    }
    _loadLocalSettings() {
        const voiceActivationThresholdString = browser.localStorage.getItem(
            "mail_user_setting_voice_threshold",
        );
        this.voiceActivationThreshold = voiceActivationThresholdString
            ? parseFloat(voiceActivationThresholdString)
            : this.voiceActivationThreshold;
        this.audioInputDeviceId =
            browser.localStorage.getItem("mail_user_setting_audio_input_device_id") ??
            "";
        this.audioOutputDeviceId =
            browser.localStorage.getItem("mail_user_setting_audio_output_device_id") ??
            "";
        this.cameraInputDeviceId =
            browser.localStorage.getItem("mail_user_setting_camera_input_device_id") ??
            "";
        this.showOnlyVideo =
            browser.localStorage.getItem("mail_user_setting_show_only_video") ===
            "true";
        const backgroundBlurAmount = browser.localStorage.getItem(
            "mail_user_setting_background_blur_amount",
        );
        this.backgroundBlurAmount = backgroundBlurAmount
            ? parseInt(backgroundBlurAmount)
            : 10;
        const edgeBlurAmount = browser.localStorage.getItem(
            "mail_user_setting_edge_blur_amount",
        );
        this.edgeBlurAmount = edgeBlurAmount ? parseInt(edgeBlurAmount) : 10;
        this.useCallAutoFocus = !browser.localStorage.getItem(
            "mail_user_setting_disable_call_auto_focus",
        );
        log.lifecycle("localSettings loaded", () => ({
            voiceActivationThreshold: this.voiceActivationThreshold,
            audioInputDeviceId: this.audioInputDeviceId,
            audioOutputDeviceId: this.audioOutputDeviceId,
            cameraInputDeviceId: this.cameraInputDeviceId,
            showOnlyVideo: this.showOnlyVideo,
            useCallAutoFocus: this.useCallAutoFocus,
        }));
    }
    async _onSaveGlobalSettingsTimeout() {
        this.globalSettingsTimeout = undefined;
        const endSave = log.perf("saveGlobalSettings");
        try {
            await this.store.env.services.orm.call(
                "res.users.settings",
                "set_res_users_settings",
                [[this.id]],
                {
                    new_settings: {
                        push_to_talk_key: this.push_to_talk_key,
                        use_push_to_talk: this.use_push_to_talk,
                        voice_active_duration: this.voice_active_duration,
                    },
                },
            );
            endSave();
        } catch {
            endSave({ failed: true });
            this.store.env.services.notification.add(
                _t("Failed to save your voice settings, please try again."),
                { type: "warning" },
            );
        }
    }
    /**
     * @param {Object} param0
     * @param {String} param0.key
     * @param {number} [param0.partnerId]
     * @param {number} [param0.guestId]
     * @param {number} param0.volume
     */
    async _onSaveVolumeSettingTimeout({ key, partnerId, guestId, volume }) {
        this.volumeSettingsTimeouts.delete(key);
        log.logic("saveVolumeSetting", () => ({ key, partnerId, guestId, volume }));
        try {
            await this.store.env.services.orm.call(
                "res.users.settings",
                "set_volume_setting",
                [[this.id], partnerId, volume],
                { guest_id: guestId },
            );
        } catch {
            log.logic("saveVolumeSetting failed", () => ({ key }));
            this.store.env.services.notification.add(
                _t("Failed to save the volume setting, please try again."),
                { type: "warning" },
            );
        }
    }
    /** @returns {() => void} */
    _watchDeviceIdsAcrossTabs() {
        const stops = Object.entries({
            mail_user_setting_audio_input_device_id: "audioInputDeviceId",
            mail_user_setting_audio_output_device_id: "audioOutputDeviceId",
            mail_user_setting_camera_input_device_id: "cameraInputDeviceId",
        }).map(([key, fieldName]) =>
            onLocalStorageChange(this.store, key, (newValue) => {
                log.logic("device id from another tab", () => ({ key, newValue }));
                this[fieldName] = newValue;
            }),
        );
        return () => stops.forEach((stop) => stop());
    }
    async _saveSettings() {
        if (!this.store.self_partner) {
            log.logic("_saveSettings skipped: no self partner");
            return;
        }
        browser.clearTimeout(this.globalSettingsTimeout);
        this.globalSettingsTimeout = browser.setTimeout(
            () => this._onSaveGlobalSettingsTimeout(),
            2000,
        );
    }
}

Settings.register();
