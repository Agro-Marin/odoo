/** @odoo-module native */
import { useChildSubEnv, useEnv, useSubEnv } from "@odoo/owl";

/** @param {Record<string, any>} context */
export function provideAccountContext(context) {
    useSubEnv(context);
}

/** @param {Record<string, any>} context */
export function provideChildAccountContext(context) {
    useChildSubEnv(context);
}

/** @returns {Record<string, any>} */
export function useAccountContext() {
    return useEnv();
}
