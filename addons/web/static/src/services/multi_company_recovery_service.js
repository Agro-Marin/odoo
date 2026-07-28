// @ts-check
/** @odoo-module native */

/** @module @web/services/multi_company_recovery_service - Recover from AccessError when the server suggests a company switch */

import { registry } from "@web/core/registry";
import { unique } from "@web/core/utils/collections/arrays";
import { user } from "@web/services/user";

/**
 * The backend tags cross-company AccessErrors with a `suggested_company` in the
 * error context; this service centralizes the matching predicate and both
 * recovery strategies (with/without reload), replacing logic that used to be
 * duplicated (and had drifted) between FormController's onError/onSaveError.
 */

/**
 * OWL lifecycle errors wrap the original in `.cause`; RPC error_service errors
 * don't. Read both shapes so callers don't need to know which path they're on.
 *
 * @param {any} error
 * @returns {any} the inner data object, or undefined if neither shape matches
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

export const multiCompanyRecoveryService = {
    /**
     * @param {import("@web/env").OdooEnv} env
     */
    start(env) {
        return {
            /**
             * Reloads the page after activating the suggested company (form data
             * is unrecoverable at this lifecycle point). Caller must pass its own
             * `env` (e.g. `this.env`) — `pushStateBeforeReload`, injected via
             * `useChildSubEnv` in `ControllerComponent`, isn't visible from the
             * service's root-env closure.
             *
             * @param {any} error
             * @param {{ inDialog?: boolean, env?: import("@web/env").OdooEnv }} [options]
             * @returns {boolean} true if the recovery applied
             *   (caller should swallow the error)
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
                /** @type {any} */ (callerEnv).pushStateBeforeReload?.();
                activeCompanyIds.push(suggestedCompany.id);
                user.activateCompanies(activeCompanyIds);
                return true;
            },

            /**
             * Recovers from a save error without reloading (unsaved input would
             * be lost): adds the suggested company to the model's context and
             * activates it client-side. Caller should retry the save after this
             * returns true.
             *
             * @param {any} error
             * @param {{ config: { context: { allowed_company_ids: number[] } } }} model
             * @returns {boolean} true if the recovery applied
             *   (caller should retry the save)
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
                const scopedIds = model.config.context.allowed_company_ids ?? [];
                const requestedIds = [...activeCompanyIds, suggestedCompany.id];
                user.activateCompanies(requestedIds, { reload: false });
                // Union of three sources, because none alone is right:
                //  - `scopedIds`  — the model may be scoped to a company the user
                //                   does not have active; overwriting would drop it.
                //  - `requestedIds` — what we asked for, so the suggested company is
                //                   present even if activation is a no-op.
                //  - the companies READ BACK from the user, which is the only source
                //    carrying the CHILDREN `activateCompanies` pulls in. Omitting
                //    them left the model context a strict subset of the user
                //    context, and the model context wins on the retried save — so a
                //    record owned by a child of the suggested company failed again
                //    with the very AccessError this recovery exists to clear.
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
