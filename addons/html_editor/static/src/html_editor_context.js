/** @odoo-module native */
import { useChildSubEnv, useEnv, useSubEnv } from "@odoo/owl";

/** @param {Record<string, any>} context */
export function provideHtmlEditorContext(context) {
    useSubEnv(context);
}

/** @param {Record<string, any>} context */
export function provideChildHtmlEditorContext(context) {
    useChildSubEnv(context);
}

/** @returns {Record<string, any>} */
export function useHtmlEditorContext() {
    return useEnv();
}
