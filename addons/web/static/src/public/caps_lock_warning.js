// @ts-check
/** @odoo-module native */

import { registry } from "@web/core/registry";
import { _t } from "@web/core/translation";
import { Interaction } from "@web/public/interaction";

export class CapsLockWarning extends Interaction {
    static selector = ".o_caps_lock_warning";
    dynamicContent = {
        ".o_caps_lock_warning_text": {
            "t-out": () => (this.isCapsLockOn ? _t("Caps Lock is on!") : ""),
        },
        _root: {
            "t-on-keydown": this._onInputKey,
            "t-on-keyup": this._onInputKey,
        },
    };

    setup() {
        this.isCapsLockOn = false;
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
        this.isCapsLockOn = state;
    }
}

registry.category("public.interactions").add("web.caps_lock_warning", CapsLockWarning);
