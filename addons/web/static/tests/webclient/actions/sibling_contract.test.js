// @ts-check

import { describe, expect, test } from "@odoo/hoot";
import { ActionManager } from "@web/webclient/actions/action_service";

/**
 * THE SIBLING CONTRACT.
 *
 * ``action_service.js`` hands itself whole to the ~10 modules it delegates to
 * (``action_executors/*``, ``breadcrumb_manager``, ``load_state``,
 * ``action_dispatch``, ``action_button_executor``, ``controller_component``,
 * ``reports/report_executor``, ``action_loader``, ``action_info_builders``,
 * ``action_cache_invalidation``), so "what may a sibling touch?" has no answer
 * in the type system and could only be re-derived by grepping.
 *
 * This file IS the answer — there is no prose copy anywhere, deliberately: one
 * would drift out of step with the assertion that enforces it. The lists below
 * are the contract, and they have teeth in both directions:
 *
 *  - {@link SANCTIONED} must all still exist, so the doc cannot silently name
 *    a member that was renamed or deleted;
 *  - the manager must expose nothing BEYOND it, so a new public-looking member
 *    has to be classified deliberately (add it to the list and to the comment,
 *    or keep it out of the siblings' reach).
 *
 * This asserts the SHAPE of the seam, not the behaviour behind it — every
 * member's behaviour is covered by the suites around it.
 */
const SANCTIONED = [
    // read-only, collaborators
    "env",
    "router",
    "navigation",
    // read-only, state
    "controllerStack",
    "dialog",
    "nextDialog",
    "breadcrumbCache",
    // public API
    "doAction",
    "doActionButton",
    "switchView",
    "restore",
    "pushState",
    // `ActionDispatch.commit()` settles the manager's pending-dispatch slot
    // the moment it publishes its stack (see f12faec6fff).
    "settlePendingDispatch",
    // internal helpers
    "_updateUI",
    "_makeController",
    "_loadAction",
    "_confirmLeave",
    "_nextId",
    "_getView",
    "_getViewInfo",
    "_getActionInfo",
    "_getActionParams",
    "_getBreadcrumbs",
    "_controllersFromState",
    "_removeDialog",
    "_executeCloseAction",
];

/**
 * Members that exist but are NOT part of the sibling seam: they are reached
 * only from within ``action_service.js`` itself, or are the service's outward
 * face to the rest of the webclient rather than to its own siblings. Listed
 * explicitly so this test fails on a NEW member rather than on every existing
 * one.
 */
const INTERNAL = [
    "constructor",
    "loadState",
    "loadAction",
    "currentController",
    "getCurrentAction",
    "ControllerComponent",
    "uninstallActionCacheInvalidation",
    "_id",
    "_skeletonDef",
    "_actionExecutors",
    // The body of `doAction`; `doAction` itself is only the wrapper that
    // announces ACTION_MANAGER:SETTLED once the dispatch is over.
    "_doAction",
    "_preprocessAction",
    "_getCurrentController",
    "_getCurrentAction",
    "_pendingDispatch",
    "_dispatchDepth",
    "_effectiveStack",
    "_computeStackIndex",
    "_topActionJsId",
    "_previousActionJsId",
    "_prepareControllerConfig",
    "_dispatchTargetNew",
    "_dispatchInline",
    "_warnDroppedOnClose",
    "_openURL",
    "_openActionInNewWindow",
];

/** Every own member of an ActionManager instance and of its prototype. */
function allMembers() {
    const am = new ActionManager(
        /** @type {any} */ ({ bus: { trigger() {} }, services: {} }),
        /** @type {any} */ ({
            current: {},
            pushState() {},
            stateToUrl: () => "",
            hideKeyFromUrl() {},
        }),
    );
    return new Set([
        ...Object.keys(am),
        ...Object.getOwnPropertyNames(ActionManager.prototype),
    ]);
}

describe.current.tags("desktop");

test("every member the sibling contract names still exists", () => {
    const members = allMembers();
    expect(SANCTIONED.filter((name) => !members.has(name))).toEqual([]);
});

test("the manager exposes nothing outside the documented surface", () => {
    const members = allMembers();
    const known = new Set([...SANCTIONED, ...INTERNAL]);
    const undeclared = [...members].filter((name) => !known.has(name)).sort();
    expect(undeclared).toEqual([], {
        message:
            "New ActionManager member(s). Decide which side of the seam they are " +
            "on: add to SANCTIONED (and to the contract comment in " +
            "action_service.js) if a sibling module reaches them, otherwise to " +
            "INTERNAL.",
    });
});

test("the sanctioned and internal lists do not overlap", () => {
    const internal = new Set(INTERNAL);
    expect(SANCTIONED.filter((name) => internal.has(name))).toEqual([]);
});
