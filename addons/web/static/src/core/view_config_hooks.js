// @ts-check
/** @odoo-module native */
import { useChildSubEnv, useEnv, useSubEnv } from "@odoo/owl";

/** @param {import("@web/views/view_config").ViewConfig & Record<string, any>} config */
export function provideViewConfig(config) {
    useSubEnv({ config });
}

/** @param {import("@web/views/view_config").ViewConfig & Record<string, any>} config */
export function provideChildViewConfig(config) {
    useChildSubEnv({ config });
}

/** @returns {import("@web/views/view_config").ViewConfig & Record<string, any>} */
export function useViewConfig() {
    return useEnv().config;
}
