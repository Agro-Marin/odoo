/** @odoo-module native */
import { useChildSubEnv, useEnv, useSubEnv } from "@odoo/owl";

/** @param {Record<string, any>} context */
export function provideWebsiteContext(context) {
    useSubEnv(context);
}

/** @param {Record<string, any>} context */
export function provideChildWebsiteContext(context) {
    useChildSubEnv(context);
}

/** @returns {Record<string, any>} */
export function useWebsiteContext() {
    return useEnv();
}
