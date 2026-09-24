/** @odoo-module native */
import { useChildSubEnv, useEnv, useSubEnv } from "@odoo/owl";

/** @param {Record<string, any>} context */
export function providePortalContext(context) {
    useSubEnv(context);
}

/** @param {Record<string, any>} context */
export function provideChildPortalContext(context) {
    useChildSubEnv(context);
}

/** @returns {Record<string, any>} */
export function usePortalContext() {
    return useEnv();
}
