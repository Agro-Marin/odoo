/** @odoo-module native */
import { useChildSubEnv, useEnv, useSubEnv } from "@odoo/owl";

/** @param {Record<string, any>} context */
export function provideWebContext(context) {
    useSubEnv(context);
}

/** @param {Record<string, any>} context */
export function provideChildWebContext(context) {
    useChildSubEnv(context);
}

/** @returns {Record<string, any>} */
export function useWebContext() {
    return useEnv();
}
