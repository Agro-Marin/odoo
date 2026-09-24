/** @odoo-module native */
import { useChildSubEnv, useEnv, useSubEnv } from "@odoo/owl";

/** @param {Record<string, any>} context */
export function provideStockContext(context) {
    useSubEnv(context);
}

/** @param {Record<string, any>} context */
export function provideChildStockContext(context) {
    useChildSubEnv(context);
}

/** @returns {Record<string, any>} */
export function useStockContext() {
    return useEnv();
}
