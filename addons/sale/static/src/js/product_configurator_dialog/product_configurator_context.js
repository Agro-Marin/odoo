/** @odoo-module native */
import { useChildSubEnv, useEnv, useSubEnv } from "@odoo/owl";

/** @param {Record<string, any>} context */
export function provideProductConfiguratorContext(context) {
    useSubEnv(context);
}

/** @param {Record<string, any>} context */
export function provideChildProductConfiguratorContext(context) {
    useChildSubEnv(context);
}

/** @returns {Record<string, any>} */
export function useProductConfiguratorContext() {
    return useEnv();
}
