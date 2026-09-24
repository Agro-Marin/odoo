/** @odoo-module native */
import { useChildSubEnv, useEnv, useSubEnv } from "@odoo/owl";

/** @param {Record<string, any>} context */
export function provideWebsiteSaleStockContext(context) {
    useSubEnv(context);
}

/** @param {Record<string, any>} context */
export function provideChildWebsiteSaleStockContext(context) {
    useChildSubEnv(context);
}

/** @returns {Record<string, any>} */
export function useWebsiteSaleStockContext() {
    return useEnv();
}
