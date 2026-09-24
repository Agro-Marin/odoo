/** @odoo-module native */
import { useChildSubEnv, useEnv, useSubEnv } from "@odoo/owl";

/** @param {Record<string, any>} context */
export function provideProductCatalogContext(context) {
    useSubEnv(context);
}

/** @param {Record<string, any>} context */
export function provideChildProductCatalogContext(context) {
    useChildSubEnv(context);
}

/** @returns {Record<string, any>} */
export function useProductCatalogContext() {
    return useEnv();
}
