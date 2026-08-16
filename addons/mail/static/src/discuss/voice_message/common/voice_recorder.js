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

export function useVoiceRecorder() {
    /** @type {MediaStream} */
    let microphone;
    /** @type {number} */
    let startTimeStamp;
    /** @type {AudioContext} */
    let audioContext;
    /** @type {MediaStreamAudioSourceNode} */
    let streamSource;
    /** @type {AudioWorkletNode} */
    let processor;
    /** @type {Mp3Encoder} */
    let encoder;

    const component = useComponent();
    const state = useState({
        limitWarning: false,
        isActionPending: false,
        recording: component.props.state?.recording ?? false,
        elapsed: "00 : 00",
        onClick() {
            if (state.recording) {
                stopRecording();
            } else {
                startRecording();
            }
        },
    });
    /** @type {ReturnType<typeof import("@web/ui/notification/notification_service").notificationService.start>} */
    const notification = useService("notification");
    const store = useService("mail.store");
    const config = { bitRate: 128 };
    onWillUnmount(() => {
        if (state.recording) {
            notification.add(_t("Voice recording stopped"), { type: "warning" });
        }
        cleanUp();
    });

    function filename() {
        return (
            "Voice-" +
            DateTime.now().toFormat("yyyy-MM-dd") +
            "-" +
            Math.floor(Math.random() * 100000) +
            ".mp3"
        );
    }

    async function startRecording() {
        if (state.isActionPending) {
            return;
        }
        state.isActionPending = true;
        if (!microphone) {
            try {
                microphone = await browser.navigator.mediaDevices.getUserMedia({
                    audio: store.settings.audioConstraints,
                });
                if (status(component) === "destroyed") {
                    cleanUp();
                    return;
                }
            } catch {
                notification.add(
                    _t('"%(hostname)s" needs to access your microphone', {
                        hostname: browser.location.host,
                    }),
                    { type: "warning" },
                );
                state.isActionPending = false;
                return;
            }
        }
        state.elapsed = "00 : 00";
        state.recording = true;
        try {
            audioContext = new browser.AudioContext();

            await loadLamejs();
            if (!state.recording || status(component) === "destroyed") {
                cleanUp();
                return;
            }
            await audioContext.audioWorklet.addModule(
                "/discuss/voice/worklet_processor",
            );
            if (!state.recording || status(component) === "destroyed") {
                cleanUp();
                return;
            }
            processor = new browser.AudioWorkletNode(audioContext, "processor");
            processor.port.onmessage = /** @param {MessageEvent} e */ (e) => {
                if (state.recording && !startTimeStamp) {
                    startTimeStamp = e.timeStamp;
                }
                if (!startTimeStamp) {
                    return;
                }
                const elapsedSeconds = Math.floor(
                    (e.timeStamp - startTimeStamp) / 1000,
                );
                const second = elapsedSeconds % 60;
                const minute = Math.floor(elapsedSeconds / 60);
                state.elapsed =
                    (minute < 10 ? "0" + minute : minute) +
                    " : " +
                    (second < 10 ? "0" + second : second);
                if (elapsedSeconds > 55 && elapsedSeconds < 60) {
                    state.limitWarning = true;
                }
                if (elapsedSeconds >= 60) {
                    notification.add(
                        _t("The duration of voice messages is limited to 1 minute."),
                        {
                            type: "warning",
                        },
                    );
                    stopRecording();
                    return;
                }
                if (!e.data) {
                    return;
                }
                _encode(e.data);
            };
            streamSource = audioContext.createMediaStreamSource(microphone);

            streamSource.connect(processor);
            processor.connect(audioContext.destination);
            config.sampleRate = audioContext.sampleRate;
            encoder = new Mp3Encoder(config);
        } catch {
            notification.add(_t("Voice recording is not available."), {
                type: "warning",
            });
            cleanUp();
        } finally {
            state.isActionPending = false;
        }
    }

    /** @param {Float32Array} data */
    function _encode(data) {
        encoder.encode(data);
    }

    function _getEncoderBuffer() {
        return encoder.finish();
    }

    /**
     * @param {BlobPart[]} buffer
     * @param {string} type
     * @returns {File}
     */
    function _makeFile(buffer, type) {
        return patchable.makeFile(new File(buffer, filename(), { type }));
    }

    function stopRecording() {
        if (!encoder) {
            cleanUp();
            return;
        }
        getMp3()
            .then((buffer) => {
                const file = _makeFile(buffer, "audio/mp3");
                if (file.size === 0) {
                    return;
                }
                component.attachmentUploader.uploadFile(file, { voice: true });
            })
            .catch(() => {});
        cleanUp();
    }

    function cleanUp() {
        if (processor && streamSource) {
            streamSource.disconnect();
            processor.disconnect();
        }
        if (audioContext && audioContext.state !== "closed") {
            audioContext.close();
        }

        startTimeStamp = false;
        microphone?.getTracks().forEach((track) => track.stop());
        microphone = null;
        encoder = null;
        state.recording = false;
        state.limitWarning = false;
    }

    async function getMp3() {
        const finalBuffer = _getEncoderBuffer();
        return new Promise((resolve, reject) => {
            if (finalBuffer.length === 0) {
                reject(new Error("No buffer to send"));
            } else {
                resolve(finalBuffer);
                encoder.clearBuffer();
            }
        });
    }

    return state;
}
