/** @odoo-module native */
import { loadBundle } from "@web/core/assets";
import { registry } from "@web/core/registry";
import { memoize } from "@web/core/utils/functions";
const loader = {
    loadLamejs: memoize(() => loadBundle("mail.assets_lamejs")),
};

export async function loadLamejs() {
    try {
        await loader.loadLamejs();
    } catch {}
}

export class VoiceMessageService {
    /** @param {import("@web/env").OdooEnv} env */
    constructor(env) {
        /** @type {import("@mail/discuss/voice_message/common/voice_player").VoicePlayer} */
        this.activePlayer = null;
    }
}

export const voiceMessageService = {
    /**
     * @param {import("@web/env").OdooEnv} env
     */
    start(env) {
        return new VoiceMessageService(env);
    },
};

registry.category("services").add("discuss.voice_message", voiceMessageService);
