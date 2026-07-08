// @ts-check
/** @odoo-module native */

/** @module @web/services/multi_company_recovery_service - Recover from AccessError when the server suggests a company switch */

import { registry } from "@web/core/registry";
import { user } from "@web/services/user";

/**
 * The Odoo backend tags AccessErrors raised cross-company with a
 * ``suggested_company`` entry in the error context, signalling the
 * client that activating that company would resolve the access check.
 * This service centralizes the matching predicate and the two
 * recovery strategies (with reload, without reload) that views need.
 *
 * The previous home of this logic was inline in ``FormController``
 * (lifecycle ``onError`` and ``onSaveError`` paths); duplication
 * across the two sites had drifted in subtle ways (different shape
 * checks, different reload semantics, different idempotency
 * guards).  Centralizing here removes the drift and makes the
 * server-driven recovery protocol testable in isolation.
 */

/**
 * The OWL component lifecycle wraps thrown errors in an ``OwlError``
 * with the original on ``.cause``.  RPC error_service handlers see
 * the unwrapped error directly.  Read both shapes so callers don't
 * have to know which path they're on.
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
             * Recover from an error raised during a component's
             * willStart / mounted / render lifecycle.  Form data is
             * unrecoverable at this point, so this strategy reloads
             * the page after activating the suggested company.
             *
             * Caller must pass its own ``env`` (typically
             * ``this.env`` from inside a component) so that
             * ``pushStateBeforeReload`` — injected via
             * ``useChildSubEnv`` in ``ControllerComponent`` — is
             * actually visible.  The service's own ``start(env)``
             * closure captures the ROOT env, which does NOT carry
             * the controller-scoped sub-env keys.
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
                    // Already active.  Activating + reloading again would just
                    // re-raise the same AccessError, spinning an infinite reload
                    // loop; this is not our recovery path.  (Mirrors the
                    // save-error guard below.)
                    return false;
                }
                /** @type {any} */ (callerEnv).pushStateBeforeReload?.();
                activeCompanyIds.push(suggestedCompany.id);
                user.activateCompanies(activeCompanyIds);
                return true;
            },

            /**
             * Recover from a save error WITHOUT reloading.  The user
             * has unsaved input on screen; reloading would discard
             * it.  Instead, mutate the model's context to include
             * the suggested company and activate it client-side
             * with reload disabled.  Caller is expected to invoke
             * the save retry callback after this returns true.
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
                    // Already active.  Save failed for a different
                    // reason; not our recovery path.
                    return false;
                }
                model.config.context.allowed_company_ids ??= [];
                model.config.context.allowed_company_ids.push(suggestedCompany.id);
                activeCompanyIds.push(suggestedCompany.id);
                user.activateCompanies(activeCompanyIds, { reload: false });
                return true;
            },
        };
    },
};

registry
    .category("services")
    .add("multi_company_recovery", multiCompanyRecoveryService);
