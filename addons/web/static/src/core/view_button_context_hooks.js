// @ts-check
/** @odoo-module native */
import { useChildSubEnv, useEnv, useSubEnv } from "@odoo/owl";

/** @param {Record<string, any>} context */
export function provideViewButtonContext(context) {
    useSubEnv(context);
}

/** @param {Record<string, any>} context */
export function provideChildViewButtonContext(context) {
    useChildSubEnv(context);
}

/** @returns {Record<string, any>} */
export function useViewButtonContext() {
    return useEnv();
}
