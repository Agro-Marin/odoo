/** @odoo-module native */
import { _t } from "@web/core/translation";

import { registerCallAction } from "@mail/discuss/call/common/call_actions";

registerCallAction("record", {
    /** @param {Object} params */
    condition: ({ owner, thread, store }) =>
        thread?.isSelfInCall &&
        !owner.env.inCallMenu &&
        store.env.services["discuss.call_recording"].isSupported,
    /** @param {Object} params */
    icon: ({ store }) =>
        store.env.services["discuss.call_recording"].state.recording
            ? "fa-solid fa-stop"
            : "fa-solid fa-circle",
    /** @param {Object} params */
    isActive: ({ store }) =>
        store.env.services["discuss.call_recording"].state.recording,
    isTracked: true,
    /** @param {Object} params */
    name: ({ store }) =>
        store.env.services["discuss.call_recording"].state.recording
            ? _t("Stop recording")
            : _t("Record"),
    /** @param {Object} params */
    onSelected: ({ store, thread }) =>
        store.env.services["discuss.call_recording"].toggle(thread),
    sequence: 25,
});
