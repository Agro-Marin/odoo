// @ts-check
/** @odoo-module native */

import { browser } from "@web/core/browser/browser";
import { registry } from "@web/core/registry";

// headless Chrome 153 answers SpeechRecognition.available() never, for any
// language: an engine that does not say within this is not available
export const AVAILABILITY_TIMEOUT_MS = 2000;

/**
 * A speech engine turns one utterance into text. The first available one, by
 * sequence, is used.
 *
 * @typedef {{
 *   lang: string,
 *   phrases: string[],
 *   onInterim: (text: string) => void,
 *   signal: AbortSignal,
 * }} ListenOptions
 * @typedef {{
 *   available: (lang: string) => Promise<boolean>,
 *   listen: (options: ListenOptions) => Promise<string>,
 *   privacy: () => string,
 * }} VoiceEngine
 */

export const voiceEngineRegistry = registry.category("voice_engines");

voiceEngineRegistry.addValidation({
    available: { type: Function },
    listen: { type: Function },
    privacy: { type: Function },
});

/**
 * @param {string} lang
 * @returns {Promise<VoiceEngine | null>}
 */
export async function firstAvailableEngine(lang) {
    for (const engine of voiceEngineRegistry.getAll()) {
        try {
            const answer = await Promise.race([
                engine.available(lang),
                new Promise((resolve) =>
                    browser.setTimeout(() => resolve(false), AVAILABILITY_TIMEOUT_MS),
                ),
            ]);
            if (answer) {
                return engine;
            }
        } catch {
            continue;
        }
    }
    return null;
}
