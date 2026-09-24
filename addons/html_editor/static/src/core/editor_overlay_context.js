/** @odoo-module native */
import { useChildSubEnv, useEnv, useSubEnv } from "@odoo/owl";

/** @param {Record<string, any>} context */
export function provideEditorOverlayContext(context) {
    useSubEnv(context);
}

/** @param {Record<string, any>} context */
export function provideChildEditorOverlayContext(context) {
    useChildSubEnv(context);
}

/** @returns {Record<string, any>} */
export function useEditorOverlayContext() {
    return useEnv();
}
