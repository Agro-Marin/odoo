// @ts-check
/** @odoo-module native */

import { browser } from "@web/core/browser/browser";
import { _t } from "@web/core/translation";

import { voiceEngineRegistry } from "./voice_engines.js";

const MAX_PHRASES = 100;
const PHRASE_BOOST = 5;

/** @returns {any} */
function recognitionClass() {
    const scope = /** @type {any} */ (browser);
    return scope.SpeechRecognition || scope.webkitSpeechRecognition || null;
}

/**
 * The browser's recogniser, on-device only: without `processLocally` a
 * browser sends the audio to its vendor, and nothing here asked for that.
 *
 * @type {import("./voice_engines.js").VoiceEngine}
 */
export const browserEngine = {
    async available(lang) {
        const Recognition = recognitionClass();
        if (typeof Recognition?.available !== "function") {
            return false;
        }
        const status = await Recognition.available({
            langs: [lang],
            processLocally: true,
        });
        return status === "available";
    },

    listen({ lang, phrases, onInterim, signal }) {
        const Recognition = recognitionClass();
        const recognition = new Recognition();
        recognition.lang = lang;
        recognition.interimResults = true;
        recognition.continuous = false;
        recognition.processLocally = true;
        const Phrase = /** @type {any} */ (browser).SpeechRecognitionPhrase;
        if (Phrase && "phrases" in recognition) {
            recognition.phrases = phrases
                .slice(0, MAX_PHRASES)
                .map((phrase) => new Phrase(phrase, PHRASE_BOOST));
        }
        return new Promise((resolve, reject) => {
            let final = "";
            recognition.onresult = (/** @type {any} */ event) => {
                let interim = "";
                for (const result of event.results) {
                    if (result.isFinal) {
                        final = result[0].transcript;
                    } else {
                        interim += result[0].transcript;
                    }
                }
                onInterim(final || interim);
            };
            recognition.onerror = (/** @type {any} */ event) => {
                if (["no-speech", "aborted"].includes(event.error)) {
                    return;
                }
                reject(new Error(event.message || event.error));
            };
            recognition.onend = () => resolve(final);
            signal.addEventListener("abort", () => recognition.stop(), { once: true });
            recognition.start();
        });
    },

    privacy() {
        return _t(
            "Your browser recognises what you say on this device; the audio does not leave it.",
        );
    },
};

voiceEngineRegistry.add("browser", browserEngine, { sequence: 50 });
