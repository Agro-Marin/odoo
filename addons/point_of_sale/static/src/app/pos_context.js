/** @odoo-module native */
import { useChildSubEnv, useEnv, useSubEnv } from "@odoo/owl";

/** @param {Record<string, any>} context */
export function providePosContext(context) {
    useSubEnv(context);
}

/** @param {Record<string, any>} context */
export function provideChildPosContext(context) {
    useChildSubEnv(context);
}

/** @returns {Record<string, any>} */
export function usePosContext() {
    return useEnv();
}
