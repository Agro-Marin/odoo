// @ts-check
/** @odoo-module native */

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
 * @param {{ id: number }} suggestedCompany
 * @returns {boolean}
 */
function _isAllowedCompany(suggestedCompany) {
    return user.allowedCompanies.some((c) => c.id === suggestedCompany.id);
}

/**
 * @param {any} error
 * @returns {any | null} the company the error names when switching to it can
 *  help: an access error naming a company not yet active that the user may use
 */
function _recoverableCompany(error) {
    const suggestedCompany = _suggestedCompany(error);
    if (!_isAccessError(error) || !suggestedCompany) {
        return null;
    }
    if (user.activeCompanies.some((c) => c.id === suggestedCompany.id)) {
        return null;
    }
    return _isAllowedCompany(suggestedCompany) ? suggestedCompany : null;
}

const multiCompanyRecoveryService = {
    /** @param {import("@web/env").OdooEnv} env */
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
                const suggestedCompany = _recoverableCompany(error);
                if (!suggestedCompany) {
                    return false;
                }
                const activeCompanyIds = user.activeCompanies.map((c) => c.id);
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
                const suggestedCompany = _recoverableCompany(error);
                if (!suggestedCompany) {
                    return false;
                }
                const activeCompanyIds = user.activeCompanies.map((c) => c.id);
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
