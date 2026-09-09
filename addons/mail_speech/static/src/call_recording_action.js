/** @odoo-module native */
import { _t } from "@web/core/translation";

import { registerCallAction } from "@mail/discuss/call/common/call_actions";

/**
 * @param {Object} store
 * @returns {import("./call_recording_service").CallRecordingService|undefined}
 */
const recording = (store) => store.env.services["discuss.call_recording"];

registerCallAction("record", {
    /** @param {Object} params */
    condition: ({ owner, thread, store }) =>
        thread?.isSelfInCall &&
        !owner.env.inCallMenu &&
        Boolean(recording(store)?.isSupported),
    /** @param {Object} params */
    icon: ({ store }) =>
        recording(store)?.state.recording ? "fa-solid fa-stop" : "fa-solid fa-circle",
    /** @param {Object} params */
    isActive: ({ store }) => Boolean(recording(store)?.state.recording),
    isTracked: true,
    /** @param {Object} params */
    name: ({ store }) =>
        recording(store)?.state.recording ? _t("Stop recording") : _t("Record"),
    /** @param {Object} params */
    onSelected: ({ store, thread }) => recording(store)?.toggle(thread),
    sequence: 25,
});
