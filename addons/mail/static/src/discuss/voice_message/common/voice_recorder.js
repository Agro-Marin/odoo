/** @odoo-module native */
import { loadLamejs } from "@mail/discuss/voice_message/common/voice_message_service";
import { onWillUnmount, status, useComponent, useState } from "@odoo/owl";
import { browser } from "@web/core/browser/browser";
import { DateTime } from "@web/core/l10n/luxon";
import { _t } from "@web/core/translation";
import { useService } from "@web/core/utils/hooks";

import { Mp3Encoder } from "./mp3_encoder.js";
export const patchable = {
    /**
     * @param {File} file
     * @returns {File}
     */
    makeFile(file) {
        return file;
    },
};

const LIMIT_WARNING_SECONDS = 55;
const LIMIT_SECONDS = 60;

function filename() {
    return (
        "Voice-" +
        DateTime.now().toFormat("yyyy-MM-dd") +
        "-" +
        Math.floor(Math.random() * 100000) +
        ".mp3"
    );
}

class VoiceRecorder {
    /** @type {MediaStream} */
    microphone;
    /** @type {number} */
    startTimeStamp;
    /** @type {AudioContext} */
    audioContext;
    /** @type {MediaStreamAudioSourceNode} */
    streamSource;
    /** @type {AudioWorkletNode} */
    processor;
    /** @type {Mp3Encoder} */
    encoder;

    constructor(component, state, notification, store) {
        this.component = component;
        this.state = state;
        this.notification = notification;
        this.store = store;
        this.config = { bitRate: 128 };
    }

    get gone() {
        return status(this.component) === "destroyed";
    }

    toggle() {
        if (this.state.recording) {
            this.stopRecording();
        } else {
            this.startRecording();
        }
    }

    async startRecording() {
        if (this.state.isActionPending) {
            return;
        }
        this.state.isActionPending = true;
        if (!this.microphone && !(await this._openMicrophone())) {
            return;
        }
        this.state.elapsed = "00 : 00";
        this.state.recording = true;
        try {
            await this._openEncoder();
        } catch {
            this.notification.add(_t("Voice recording is not available."), {
                type: "warning",
            });
            this.cleanUp();
        } finally {
            this.state.isActionPending = false;
        }
    }

    /** @returns {Promise<boolean>} whether recording may proceed */
    async _openMicrophone() {
        try {
            this.microphone = await browser.navigator.mediaDevices.getUserMedia({
                audio: this.store.settings.audioConstraints,
            });
        } catch {
            this.notification.add(
                _t('"%(hostname)s" needs to access your microphone', {
                    hostname: browser.location.host,
                }),
                { type: "warning" },
            );
            this.state.isActionPending = false;
            return false;
        }
        if (this.gone) {
            this.cleanUp();
            return false;
        }
        return true;
    }

    async _openEncoder() {
        this.audioContext = new browser.AudioContext();

        await loadLamejs();
        if (!this.state.recording || this.gone) {
            this.cleanUp();
            return;
        }
        await this.audioContext.audioWorklet.addModule(
            "/discuss/voice/worklet_processor",
        );
        if (!this.state.recording || this.gone) {
            this.cleanUp();
            return;
        }
        this.processor = new browser.AudioWorkletNode(this.audioContext, "processor");
        this.processor.port.onmessage = (e) => this._onProcessorMessage(e);
        this.streamSource = this.audioContext.createMediaStreamSource(this.microphone);

        this.streamSource.connect(this.processor);
        this.processor.connect(this.audioContext.destination);
        this.config.sampleRate = this.audioContext.sampleRate;
        this.encoder = new Mp3Encoder(this.config);
    }

    /** @param {MessageEvent} e */
    _onProcessorMessage(e) {
        if (this.state.recording && !this.startTimeStamp) {
            this.startTimeStamp = e.timeStamp;
        }
        if (!this.startTimeStamp) {
            return;
        }
        const elapsedSeconds = Math.floor((e.timeStamp - this.startTimeStamp) / 1000);
        const second = elapsedSeconds % 60;
        const minute = Math.floor(elapsedSeconds / 60);
        this.state.elapsed =
            (minute < 10 ? "0" + minute : minute) +
            " : " +
            (second < 10 ? "0" + second : second);
        if (elapsedSeconds > LIMIT_WARNING_SECONDS && elapsedSeconds < LIMIT_SECONDS) {
            this.state.limitWarning = true;
        }
        if (elapsedSeconds >= LIMIT_SECONDS) {
            this.notification.add(
                _t("The duration of voice messages is limited to 1 minute."),
                {
                    type: "warning",
                },
            );
            this.stopRecording();
            return;
        }
        if (!e.data) {
            return;
        }
        this.encoder.encode(e.data);
    }

    /**
     * @param {BlobPart[]} buffer
     * @param {string} type
     * @returns {File}
     */
    _makeFile(buffer, type) {
        return patchable.makeFile(new File(buffer, filename(), { type }));
    }

    stopRecording() {
        if (!this.encoder) {
            this.cleanUp();
            return;
        }
        this.getMp3()
            .then((buffer) => {
                const file = this._makeFile(buffer, "audio/mp3");
                if (file.size === 0) {
                    return;
                }
                this.component.attachmentUploader.uploadFile(file, { voice: true });
            })
            .catch(() => {});
        this.cleanUp();
    }

    cleanUp() {
        if (this.processor && this.streamSource) {
            this.streamSource.disconnect();
            this.processor.disconnect();
        }
        if (this.audioContext && this.audioContext.state !== "closed") {
            this.audioContext.close();
        }

        this.startTimeStamp = false;
        this.microphone?.getTracks().forEach((track) => track.stop());
        this.microphone = null;
        this.encoder = null;
        this.state.recording = false;
        this.state.limitWarning = false;
    }

    async getMp3() {
        const finalBuffer = this.encoder.finish();
        return new Promise((resolve, reject) => {
            if (finalBuffer.length === 0) {
                reject(new Error("No buffer to send"));
            } else {
                resolve(finalBuffer);
                this.encoder.clearBuffer();
            }
        });
    }

    dispose() {
        if (this.state.recording) {
            this.notification.add(_t("Voice recording stopped"), { type: "warning" });
        }
        this.cleanUp();
    }
}

export function useVoiceRecorder() {
    const component = useComponent();
    const state = useState({
        limitWarning: false,
        isActionPending: false,
        recording: component.props.state?.recording ?? false,
        elapsed: "00 : 00",
        onClick() {
            recorder.toggle();
        },
    });
    const recorder = new VoiceRecorder(
        component,
        state,
        useService("notification"),
        useService("mail.store"),
    );
    onWillUnmount(() => recorder.dispose());
    return state;
}
