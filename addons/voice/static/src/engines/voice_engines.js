// @ts-check
/** @odoo-module native */

import { registry } from "@web/core/registry";

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
            if (await engine.available(lang)) {
                return engine;
            }
        } catch {
            continue;
        }
    }
    return null;
}
