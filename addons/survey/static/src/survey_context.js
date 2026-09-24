/** @odoo-module native */
import { useChildSubEnv, useEnv, useSubEnv } from "@odoo/owl";

/** @param {Record<string, any>} context */
export function provideSurveyContext(context) {
    useSubEnv(context);
}

/** @param {Record<string, any>} context */
export function provideChildSurveyContext(context) {
    useChildSubEnv(context);
}

/** @returns {Record<string, any>} */
export function useSurveyContext() {
    return useEnv();
}
