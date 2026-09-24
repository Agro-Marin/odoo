/** @odoo-module native */
import { useChildSubEnv, useEnv, useSubEnv } from "@odoo/owl";

/** @param {Record<string, any>} context */
export function provideDocModelStore(context) {
    useSubEnv(context);
}

/** @param {Record<string, any>} context */
export function provideChildDocModelStore(context) {
    useChildSubEnv(context);
}

/** @returns {Record<string, any>} */
export function useDocModelStore() {
    return useEnv();
}
