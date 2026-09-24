/** @odoo-module native */
import { useChildSubEnv, useEnv, useSubEnv } from "@odoo/owl";

/** @param {Record<string, any>} context */
export function provideAppointmentCalendarContext(context) {
    useSubEnv(context);
}

/** @param {Record<string, any>} context */
export function provideChildAppointmentCalendarContext(context) {
    useChildSubEnv(context);
}

/** @returns {Record<string, any>} */
export function useAppointmentCalendarContext() {
    return useEnv();
}
