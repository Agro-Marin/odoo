// @ts-check

import { describe, expect, test } from "@odoo/hoot";
import { ActionManager } from "@web/webclient/actions/action_service";
import { ACTION_MANAGER_SURFACE } from "@web/webclient/actions/action_service_contract";

const SANCTIONED = ACTION_MANAGER_SURFACE;

const INTERNAL = [
    "constructor",
    "ControllerComponent",
    "_id",
    "_actionExecutors",
    "_doAction",
    "_preprocessAction",
    "getCurrentAction",
    "dialogService",
    "_pendingDispatch",
    "_dispatchDepth",
    "_effectiveStack",
    "_computeStackIndex",
    "_topActionJsId",
    "_previousActionJsId",
    "_prepareControllerConfig",
    "_dispatchTargetNew",
    "_dispatchInline",
    "_awaitSkeletonMount",
    "_warnDroppedOnClose",
    "_openURL",
    "_openActionInNewWindow",
];

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
            "on: add to ACTION_MANAGER_SURFACE in action_service_contract.js if " +
            "anything outside the class reaches them, otherwise to INTERNAL here.",
    });
});

test("the sanctioned and internal lists do not overlap", () => {
    const internal = new Set(INTERNAL);
    expect(SANCTIONED.filter((name) => internal.has(name))).toEqual([]);
});
