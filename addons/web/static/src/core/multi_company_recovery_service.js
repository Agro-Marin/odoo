// @ts-check
/** @odoo-module native */

/** @module @web/core/multi_company_recovery_service */

import { registry } from "@web/core/registry";
import { user } from "@web/core/user";
import { unique } from "@web/core/utils/collections/arrays";

/**
 * @param {any} error
 * @returns {any}
 */
function _errorData(error) {
    return error?.data ?? error?.cause?.data;
}

/**
 * @param {any} error
 * @returns {boolean}
 */
function _isAccessError(error) {
    return _errorData(error)?.name === "odoo.exceptions.AccessError";
}

/**
 * @param {any} error
 * @returns {{ id: number; [key: string]: any } | undefined}
 */
function _suggestedCompany(error) {
    return _errorData(error)?.context?.suggested_company;
}

/**
 * Whether the user is actually allowed to activate the given company. The
 * backend suggestion is advisory: activating a company outside the allowed
 * set would be silently filtered out by the user service, causing an endless
 * error -> reload loop.
 *
 * @param {{ id: number }} suggestedCompany
 * @returns {boolean}
 */
function _isAllowedCompany(suggestedCompany) {
    return user.allowedCompanies.some((c) => c.id === suggestedCompany.id);
}

export const multiCompanyRecoveryService = {
    /**
     * @param {import("@web/env").OdooEnv} env
     */
    start(env) {
        return {
            /**
             * @param {any} error
             * @param {{ inDialog?: boolean, env?: import("@web/env").OdooEnv }} [options]
             * @returns {boolean}
             */
            recoverFromLifecycleError(
                error,
                { inDialog = false, env: callerEnv = env } = {},
            ) {
                if (inDialog) {
                    return false;
                }
                const suggestedCompany = _suggestedCompany(error);
                if (!_isAccessError(error) || !suggestedCompany) {
                    return false;
                }
                const activeCompanyIds = user.activeCompanies.map((c) => c.id);
                if (activeCompanyIds.includes(suggestedCompany.id)) {
                    return false;
                }
                if (!_isAllowedCompany(suggestedCompany)) {
                    return false;
                }
                /** @type {any} */ (callerEnv).pushStateBeforeReload?.();
                activeCompanyIds.push(suggestedCompany.id);
                user.activateCompanies(activeCompanyIds);
                return true;
            },

            /**
             * @param {any} error
             * @param {{ config: { context: { allowed_company_ids: number[] } } }} model
             * @returns {boolean}
             */
            recoverFromSaveError(error, model) {
                const suggestedCompany = _suggestedCompany(error);
                if (!_isAccessError(error) || !suggestedCompany) {
                    return false;
                }
                const activeCompanyIds = user.activeCompanies.map((c) => c.id);
                if (activeCompanyIds.includes(suggestedCompany.id)) {
                    return false;
                }
                if (!_isAllowedCompany(suggestedCompany)) {
                    return false;
                }
                const scopedIds = model.config.context.allowed_company_ids ?? [];
                const requestedIds = [...activeCompanyIds, suggestedCompany.id];
                user.activateCompanies(requestedIds, { reload: false });
                model.config.context.allowed_company_ids = unique([
                    ...scopedIds,
                    ...requestedIds,
                    ...user.activeCompanies.map((c) => c.id),
                ]);
                return true;
            },
        };
    },
};

registry
    .category("services")
    .add("multi_company_recovery", multiCompanyRecoveryService);
