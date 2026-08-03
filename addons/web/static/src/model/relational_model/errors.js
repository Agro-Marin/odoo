// @ts-check
/** @odoo-module native */

/** @module @web/model/relational_model/errors */

import { registry } from "@web/core/registry";
import { _t } from "@web/core/translation";
export class FetchRecordError extends Error {
    /**
     * @param {number[]} resIds
     */
    constructor(resIds) {
        super(
            _t(
                "It seems the records with IDs %s cannot be found. They might have been deleted.",
                resIds,
            ),
        );
        this.resIds = resIds;
    }
}
/**
 * @param {import("@web/env").OdooEnv} env
 * @param {Error} error
 * @param {Error} originalError
 * @returns {boolean | void}
 */
function fetchRecordErrorHandler(env, error, originalError) {
    if (originalError instanceof FetchRecordError) {
        env.services.notification.add(originalError.message, {
            sticky: true,
            type: "danger",
        });
        return true;
    }
}
const errorHandlerRegistry = registry.category("error_handlers");
errorHandlerRegistry.add("fetchRecordErrorHandler", fetchRecordErrorHandler);
