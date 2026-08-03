// @ts-check
/** @odoo-module native */

/** @module @web/components/datetime/datetime_picker_hook */

import { useRef } from "@odoo/owl";
import { useService } from "@web/core/utils/hooks";
/**
 * @typedef {import("@web/components/datetime/datetime_picker_service").DateTimePickerServiceParams & {
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

    const serviceParams = Object.assign(Object.create(params), {
        getInputs,
        useOwlHooks: true,
    });

    return useService("datetime_picker").create(serviceParams);
}
