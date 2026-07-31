// @ts-check
/** @odoo-module native */

/** @module @web/public/caps_lock_warning */

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
     * @private
     * @param {KeyboardEvent} ev
     */
    _onInputKey(ev) {
        const state = ev.getModifierState?.("CapsLock");
        if (state === undefined) {
            return;
        }
        if (ev.type === "keydown" && ev.key === "CapsLock") {
            return;
        }
        this.isWarningHidden = !state;
    }
}

registry.category("public.interactions").add("web.caps_lock_warning", CapsLockWarning);
