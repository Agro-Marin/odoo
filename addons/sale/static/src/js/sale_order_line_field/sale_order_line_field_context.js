/** @odoo-module native */
import { useChildSubEnv, useEnv, useSubEnv } from "@odoo/owl";

/** @param {Record<string, any>} context */
export function provideSaleOrderLineFieldContext(context) {
    useSubEnv(context);
}

/** @param {Record<string, any>} context */
export function provideChildSaleOrderLineFieldContext(context) {
    useChildSubEnv(context);
}

/** @returns {Record<string, any>} */
export function useSaleOrderLineFieldContext() {
    return useEnv();
}
