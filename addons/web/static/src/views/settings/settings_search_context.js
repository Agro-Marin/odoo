/** @odoo-module native */
import { useChildSubEnv, useEnv, useSubEnv } from "@odoo/owl";

/** @param {Record<string, any>} context */
export function provideSettingsSearchContext(context) {
    useSubEnv(context);
}

/** @param {Record<string, any>} context */
export function provideChildSettingsSearchContext(context) {
    useChildSubEnv(context);
}

/** @returns {Record<string, any>} */
export function useSettingsSearchContext() {
    return useEnv();
}
