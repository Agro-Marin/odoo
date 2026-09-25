// @ts-check
/** @odoo-module native */

import { Component, useState } from "@odoo/owl";
import { useHotkey } from "@web/core/hotkeys/hotkey_hook";
import { registry } from "@web/core/registry";
import { _t } from "@web/core/translation";
import { useService } from "@web/core/utils/hooks";

export const VOICE_HOTKEY = "alt+shift+v";

export class VoiceSystray extends Component {
    static template = "voice.VoiceSystray";
    static props = {};

    setup() {
        this.voice = /** @type {import("../voice_service.js").VoiceService} */ (
            useService("voice")
        );
        this.state = useState(this.voice.state);
        useHotkey(VOICE_HOTKEY, () => this.voice.listen(), {
            global: true,
            bypassEditableProtection: true,
        });
    }

    /** @returns {boolean} */
    get active() {
        return this.state.listening || Boolean(this.state.session);
    }

    /** @returns {string} */
    get title() {
        return this.active
            ? _t("Stop listening (Alt+Shift+V)")
            : _t("Speak a command (Alt+Shift+V)");
    }

    toggle() {
        this.voice.listen();
    }
}

registry
    .category("systray")
    .add("voice.systray", { Component: VoiceSystray }, { sequence: 29 });
