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
        ".o_caps_lock_warning input[type='password']": {
            "t-on-keydown": this._onInputKeyDown,
        },
    };

    setup() {
        this.isWarningHidden = true;
        this.renderAt("web.caps_lock_warning");
    }

    /**
     * Detects Caps Lock state on keydown and toggles the warning.
     *
     * @private
     * @param {KeyboardEvent} ev
     */
    _onInputKeyDown(ev) {
        // FALSE on the keydown that first turns CAPS-LOCK on (state hasn't flipped yet).
        const state = ev.getModifierState?.("CapsLock");

        // FALSE removes the `invisible` class, TRUE adds it.
        this.isWarningHidden = ev.key === "CapsLock" ? state : !state;
    }
}

registry.category("public.interactions").add("web.caps_lock_warning", CapsLockWarning);
