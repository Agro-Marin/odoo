/** @odoo-module native */
import { useChildSubEnv, useEnv } from "@odoo/owl";

/** @param {Record<string, any>} context */
export function provideChildDialogContext(context) {
    useChildSubEnv(context);
}

/** @returns {Record<string, any>} */
export function useDialogContext() {
    return useEnv();
}
