/** @odoo-module native */
import { useChildSubEnv, useEnv, useSubEnv } from "@odoo/owl";

/** @param {Record<string, any>} context */
export function provideBuilderContext(context) {
    useSubEnv(context);
}

/** @param {Record<string, any>} context */
export function provideChildBuilderContext(context) {
    useChildSubEnv(context);
}

/** @returns {Record<string, any>} */
export function useBuilderContext() {
    return useEnv();
}
