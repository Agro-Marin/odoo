/** @odoo-module native */
import { useChildSubEnv, useEnv, useSubEnv } from "@odoo/owl";

/** @param {Record<string, any>} context */
export function providePosSelfOrderContext(context) {
    useSubEnv(context);
}

/** @param {Record<string, any>} context */
export function provideChildPosSelfOrderContext(context) {
    useChildSubEnv(context);
}

/** @returns {Record<string, any>} */
export function usePosSelfOrderContext() {
    return useEnv();
}
