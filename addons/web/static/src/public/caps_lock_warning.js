// @ts-check
/** @odoo-module native */

/** @module @web/public/caps_lock_warning - Interaction that detects Caps Lock state and toggles a warning on password inputs */

import { registry } from "@web/core/registry";
import { Interaction } from "@web/public/interaction";

export class CapsLockWarning extends Interaction {
    static selector = ".o_caps_lock_warning";
    dynamicContent = {
        ".o_caps_lock_warning_text": {
            "t-att-class": () => ({ "d-none": this.isWarningHidden }),
        },
        "input[type='password']": {
            "t-on-keydown": this._onInputKey,
            "t-on-keyup": this._onInputKey,
        },
    };

    setup() {
        this.isWarningHidden = true;
        this.renderAt("web.caps_lock_warning");
    }

    /**
     * Reads the Caps Lock state off any key event in the field and toggles the
     * warning.
     *
     * @private
     * @param {KeyboardEvent} ev
     */
    _onInputKey(ev) {
        const state = ev.getModifierState?.("CapsLock");
        if (state === undefined) {
            return;
        }
        if (ev.type === "keydown" && ev.key === "CapsLock") {
            // browsers disagree on whether the Caps Lock key's own keydown
            // reports the state from before or after the toggle; its keyup is
            // unambiguous everywhere, so wait for that one reading instead of
            // guessing which convention this browser follows
            return;
        }
        this.isWarningHidden = !state;
    }
}

registry.category("public.interactions").add("web.caps_lock_warning", CapsLockWarning);
