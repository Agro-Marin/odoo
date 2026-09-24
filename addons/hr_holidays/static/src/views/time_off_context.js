/** @odoo-module native */
import { useChildSubEnv, useEnv, useSubEnv } from "@odoo/owl";

/** @param {Record<string, any>} context */
export function provideTimeOffContext(context) {
    useSubEnv(context);
}

/** @param {Record<string, any>} context */
export function provideChildTimeOffContext(context) {
    useChildSubEnv(context);
}

/** @returns {Record<string, any>} */
export function useTimeOffContext() {
    return useEnv();
}
