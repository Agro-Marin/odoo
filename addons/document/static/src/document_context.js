/** @odoo-module native */
import { useChildSubEnv, useEnv, useSubEnv } from "@odoo/owl";

/** @param {Record<string, any>} context */
export function provideDocumentContext(context) {
    useSubEnv(context);
}

/** @param {Record<string, any>} context */
export function provideChildDocumentContext(context) {
    useChildSubEnv(context);
}

/** @returns {Record<string, any>} */
export function useDocumentContext() {
    return useEnv();
}
