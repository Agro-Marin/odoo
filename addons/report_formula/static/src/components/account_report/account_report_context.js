/** @odoo-module native */
import { useChildSubEnv, useEnv, useSubEnv } from "@odoo/owl";

/** @param {Record<string, any>} context */
export function provideAccountReportContext(context) {
    useSubEnv(context);
}

/** @param {Record<string, any>} context */
export function provideChildAccountReportContext(context) {
    useChildSubEnv(context);
}

/** @returns {Record<string, any>} */
export function useAccountReportContext() {
    return useEnv();
}
