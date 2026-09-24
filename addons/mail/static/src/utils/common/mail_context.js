/** @odoo-module native */
import { useChildSubEnv, useEnv, useSubEnv } from "@odoo/owl";

/** @param {Record<string, any>} context */
export function provideMailContext(context) {
    useSubEnv(context);
}

/** @param {Record<string, any>} context */
export function provideChildMailContext(context) {
    useChildSubEnv(context);
}

/** @returns {Record<string, any>} */
export function useMailContext() {
    return useEnv();
}
