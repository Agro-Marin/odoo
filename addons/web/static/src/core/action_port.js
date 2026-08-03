// @ts-check
/** @odoo-module native */

/** @module @web/core/action_port */

import { useService } from "@web/core/utils/hooks";

/**
 * The consumer-facing surface of the `action` service.
 *
 * The service is implemented in `@web/webclient/actions/action_service` because
 * it owns the breadcrumb stack, the URL and the controller stack — all page-layer
 * concerns. Its *interface* is not a page-layer concern: `core/`, `components/`,
 * `fields/`, `search/` and `views/` all need to launch an action, and reaching
 * the implementation directly makes each of them depend upward on `webclient/`.
 *
 * This port publishes that interface at the bottom of the stack so consumers
 * depend on the contract instead. The one remaining upward edge is here, named
 * and deliberate, rather than spread across 26 call sites — see
 * `tooling/architecture/js_registry_layering.py`.
 *
 * The surface is deliberately narrower than the service: three methods, which
 * is what the 26 migrated consumers actually called. Widening it is a decision,
 * not an accident — `Pick` makes a fourth method a typecheck failure rather
 * than a silent new coupling.
 *
 * @typedef {Pick<
 *     import("services").ServiceFactories["action"],
 *     "doAction" | "doActionButton" | "switchView"
 * >} ActionPort
 */

/**
 * @returns {ActionPort}
 */
export function useAction() {
    return useService("action");
}

/**
 * The non-hook form, for helpers that receive `env` rather than run in a
 * component's setup.
 *
 * @param {import("@web/env").OdooEnv} env
 * @returns {ActionPort}
 */
export function getAction(env) {
    return env.services.action;
}
