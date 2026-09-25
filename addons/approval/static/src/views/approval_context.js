/** @odoo-module native */
import { useChildSubEnv, useEnv, useSubEnv } from "@odoo/owl";

/** @param {Record<string, any>} context */
export function provideApprovalContext(context) {
    useSubEnv(context);
}

/** @param {Record<string, any>} context */
export function provideChildApprovalContext(context) {
    useChildSubEnv(context);
}

/** @returns {Record<string, any>} */
export function useApprovalContext() {
    return useEnv();
}
