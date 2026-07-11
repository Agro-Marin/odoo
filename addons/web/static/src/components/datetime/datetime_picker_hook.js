// @ts-check
/** @odoo-module native */

/** @module @web/components/datetime/datetime_picker_hook - Hook that wires input refs to the datetime picker service */

import { useRef } from "@odoo/owl";
import { useService } from "@web/core/utils/hooks";
/**
 * @typedef {import("./datetime_picker_service").DateTimePickerServiceParams & {
 *  endDateRefName?: string;
 *  startDateRefName?: string;
 * }} DateTimePickerHookParams
 */

/**
 * @param {DateTimePickerHookParams} params
 */
export function useDateTimePicker(params) {
    function getInputs() {
        return inputRefs.map((ref) => ref.el);
    }

    const inputRefs = [
        useRef(params.startDateRefName || "start-date"),
        useRef(params.endDateRefName || "end-date"),
    ];

    // Need original object since 'pickerProps' (or any other param) can be defined
    // as getters
    const serviceParams = Object.assign(Object.create(params), {
        getInputs,
        useOwlHooks: true,
    });

    // With `useOwlHooks` the service auto-registers an onWillDestroy that
    // disposes the picker (popover teardown + registration release).
    return useService("datetime_picker").create(serviceParams);
}
