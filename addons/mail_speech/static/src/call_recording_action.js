/** @odoo-module native */
import { _t } from "@web/core/translation";

import { registerCallAction } from "@mail/discuss/call/common/call_actions";

/**
 * The recording service depends on `discuss.rtc`, and a bundle that never
 * evaluates that provider leaves it undefined rather than absent -- so every
 * read here is guarded. Without this an action definition evaluated during
 * store startup takes the whole store down with it.
 *
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
