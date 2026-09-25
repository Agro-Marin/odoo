// @ts-check
/** @odoo-module native */

import { ChunkRecorder, rms, SILENCE_RMS } from "@speech/live_capture/chunk_recorder";
import { rpc } from "@web/core/network";
import { _t } from "@web/core/translation";
import { voiceEngineRegistry } from "@voice/engines/voice_engines";

export const MAX_UTTERANCE_S = 15;
export const END_OF_SPEECH_S = 0.8;
const MAX_PROMPT_PHRASES = 50;

/**
 * One utterance: it ends at the first pause after speech, when it runs too
 * long, or when the caller stops it, and it is sent whole.
 */
export class UtteranceRecorder extends ChunkRecorder {
    /** @param {(chunk: import("@speech/live_capture/chunk_recorder").Chunk) => void} onChunk */
    constructor(onChunk) {
        super(onChunk);
        this.spoke = false;
        /** @type {() => void} */
        this.onEnd = () => {};
    }

    /** @param {Float32Array} frame */
    feed(frame) {
        this.frames.push(frame);
        this.length += frame.length;
        const loud = rms(frame) >= SILENCE_RMS;
        this.spoke ||= loud;
        this.quiet = loud ? 0 : this.quiet + frame.length;
        const seconds = this.length / this.sampleRate;
        if (
            seconds >= MAX_UTTERANCE_S ||
            (this.spoke && this.quiet >= END_OF_SPEECH_S * this.sampleRate)
        ) {
            this.onEnd();
        }
    }
}

/** @type {import("@voice/engines/voice_engines").VoiceEngine} */
export const serverEngine = {
    async available() {
        if (!navigator.mediaDevices?.getUserMedia) {
            return false;
        }
        const { available } = await rpc("/speech_voice/available");
        return available;
    },

    async listen({ lang, phrases, onInterim, signal }) {
        /** @type {import("@speech/live_capture/chunk_recorder").Chunk | null} */
        let utterance = null;
        const recorder = new UtteranceRecorder((chunk) => {
            utterance = chunk;
        });
        const ended = new Promise((resolve) => {
            recorder.onEnd = () => resolve(undefined);
            signal.addEventListener("abort", () => resolve(undefined), { once: true });
        });
        await recorder.start();
        await ended;
        await recorder.stop();
        if (!utterance) {
            return "";
        }
        onInterim(_t("Transcribing…"));
        const { text } = await rpc("/speech_voice/transcribe", {
            audio: /** @type {any} */ (utterance).audio,
            language: lang.split("-")[0],
            prompt: phrases.slice(0, MAX_PROMPT_PHRASES).join(", "),
        });
        return text;
    },

    privacy() {
        return _t(
            "What you say is sent to this Odoo server and transcribed there, or by the speech service your administrator allowed for voice commands. Neither the audio nor the words are kept.",
        );
    },
};

voiceEngineRegistry.add("server", serverEngine, { sequence: 60 });
