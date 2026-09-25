// @ts-check
/** @odoo-module native */
import { useChildSubEnv, useEnv, useSubEnv } from "@odoo/owl";

/** @typedef {import("@web/search/search_model").SearchModel} SearchModel */

/** @param {SearchModel} searchModel */
export function provideSearchModel(searchModel) {
    useSubEnv({ searchModel });
}

/** @param {SearchModel} searchModel */
export function provideChildSearchModel(searchModel) {
    useChildSubEnv({ searchModel });
}

/** @returns {SearchModel} */
export function useSearchModel() {
    return useEnv().searchModel;
}
